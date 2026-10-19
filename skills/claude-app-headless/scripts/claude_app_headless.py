#!/usr/bin/env python3
"""Local, same-task Claude Desktop peer messaging. No UI or network listener.

Adapter verified against Claude Desktop's bundled Code 2.1.299, peerProtocol=1.
The inbox is documented; the full frame is version-specific. No auth keys are
read and no permission-class/own-child claim is sent. Native inbound rules apply.
"""
import argparse
import contextlib
import ctypes
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
import subprocess
import sys
import time
import uuid

VERIFIED_VERSIONS = {'2.1.299'}
NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$')
MAX_PROMPT = 65536
MAX_SCAN = 16 * 1024 * 1024
FINAL = {'completed', 'model_mismatch', 'permission_mode_mismatch',
         'permission_mode_unverified', 'interleaved', 'transcript_changed', 'not_sent'}


class BridgeError(Exception):
    def __init__(self, code, message=''):
        self.code = code
        super().__init__(code + (': ' + message if message else ''))


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def encode_cwd(cwd):
    return re.sub(r'[^A-Za-z0-9]', '-', cwd)


def checked_name(value):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise BridgeError('INVALID_IDENTIFIER')
    return value


def safe_open(path, private=False):
    path = Path(path)
    try:
        before = path.lstat()
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as e:
        raise BridgeError('UNSAFE_FILE', e.__class__.__name__) from None
    st = os.fstat(fd)
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
            or st.st_mode & (0o077 if private else 0o022)
            or (before.st_dev, before.st_ino) != (st.st_dev, st.st_ino)):
        os.close(fd)
        raise BridgeError('UNSAFE_FILE')
    return fd, st


def read_json(path, private=False):
    fd, st = safe_open(path, private)
    with os.fdopen(fd, 'r') as f:
        if st.st_size > 2 * 1024 * 1024:
            raise BridgeError('FILE_LIMIT')
        try:
            return json.load(f)
        except (ValueError, UnicodeError):
            raise BridgeError('CORRUPT_STATE') from None


def check_dir(path, private=False):
    try:
        st = Path(path).lstat()
    except OSError:
        raise BridgeError('UNSAFE_DIRECTORY') from None
    if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid()
            or st.st_mode & (0o077 if private else 0o022)):
        raise BridgeError('UNSAFE_DIRECTORY')


def atomic_json(path, data):
    path = Path(path)
    check_dir(path.parent, private=True)
    if os.path.lexists(path):
        fd, _ = safe_open(path, private=True)
        os.close(fd)
    tmp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, ensure_ascii=False)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def screen_locked():
    """Read lock state; never lock, unlock, wake, capture or inject UI events."""
    if sys.platform != 'darwin':
        return None
    ds = key = None
    try:
        cg = ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
        cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        cg.CGSessionCopyCurrentDictionary.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        cf.CFDictionaryGetValue.restype = ctypes.c_void_p
        cf.CFBooleanGetValue.argtypes = [ctypes.c_void_p]
        cf.CFBooleanGetValue.restype = ctypes.c_bool
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        ds = cg.CGSessionCopyCurrentDictionary()
        if not ds:
            return None
        key = cf.CFStringCreateWithCString(None, b'CGSSessionScreenIsLocked', 0x08000100)
        value = cf.CFDictionaryGetValue(ds, key)
        return bool(cf.CFBooleanGetValue(value)) if value else False
    except (OSError, AttributeError):
        return None
    finally:
        if key:
            cf.CFRelease(key)
        if ds:
            cf.CFRelease(ds)


def text_of(record):
    value = record.get('message', {}).get('content', '')
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return '\n'.join(x.get('text', '') for x in value
                         if isinstance(x, dict) and x.get('type') == 'text')
    return ''


def transcript_rows(path, offset=None):
    fd, st = safe_open(path)
    with os.fdopen(fd, 'rb') as f:
        start = max(0, st.st_size - MAX_SCAN) if offset is None else offset
        if start < 0 or st.st_size - start > MAX_SCAN:
            raise BridgeError('READBACK_LIMIT')
        f.seek(start)
        if offset is None and start:
            f.readline()
        rows = []
        for line in f:
            if not line.endswith(b'\n'):
                break
            try:
                item = json.loads(line)
            except (ValueError, UnicodeError):
                raise BridgeError('TRANSCRIPT_INVALID') from None
            if isinstance(item, dict):
                rows.append(item)
    return rows, st


class Bridge:
    def __init__(self, claude_root=None, state_root=None):
        self.claude = Path(claude_root or Path.home()/'.claude')
        self.state = Path(state_root or Path.home()/'.local/state/codex-claude-app')
        self.socket_roots = [Path('/tmp/cc-socks'), Path('/tmp')/f'cc-socks-{os.getuid()}']

    @contextlib.contextmanager
    def locked(self):
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        check_dir(self.state, private=True)
        (self.state/'requests').mkdir(exist_ok=True, mode=0o700)
        check_dir(self.state/'requests', private=True)
        fd = os.open(self.state/'.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        st = os.fstat(fd)
        if st.st_uid != os.getuid() or st.st_mode & 0o077 or not stat.S_ISREG(st.st_mode):
            os.close(fd)
            raise BridgeError('UNSAFE_LOCK')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def _records(self):
        check_dir(self.claude/'sessions', private=True)
        result = []
        for p in (self.claude/'sessions').glob('*.json'):
            if not p.stem.isdigit():
                continue
            r = read_json(p)
            if r.get('entrypoint') != 'claude-desktop':
                continue
            if r.get('pid') != int(p.stem):
                raise BridgeError('PID_RECORD_MISMATCH')
            result.append(r)
        return result

    def _check_process(self, r):
        if sys.platform != 'darwin':
            raise BridgeError('MACOS_REQUIRED')
        pid = int(r['pid'])
        try:
            os.kill(pid, 0)
        except OSError:
            raise BridgeError('SESSION_NOT_RUNNING') from None
        lib = ctypes.CDLL('/usr/lib/libproc.dylib')
        buf = ctypes.create_string_buffer(4096)
        if lib.proc_pidpath(pid, buf, len(buf)) <= 0:
            raise BridgeError('PROCESS_UNVERIFIED')
        executable = Path(buf.value.decode())
        expected_root = Path.home()/'Library/Application Support/Claude/claude-code'
        if (not executable.is_relative_to(expected_root)
                or executable.name != 'claude' or r['version'] not in executable.parts):
            raise BridgeError('NOT_DESKTOP_RUNTIME')
        env = dict(os.environ, TZ='UTC', LC_ALL='C')
        p = subprocess.run(['ps', '-p', str(pid), '-o', 'lstart='], env=env,
                           capture_output=True, text=True, timeout=3)
        if ' '.join(p.stdout.split()) != ' '.join(str(r.get('procStart', '')).split()):
            raise BridgeError('PID_REUSED_OR_START_CHANGED')

    def _socket(self, r):
        p = Path(r.get('messagingSocketPath', ''))
        try:
            st = p.lstat()
        except OSError:
            raise BridgeError('UNSAFE_SOCKET') from None
        if (not stat.S_ISSOCK(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077
                or p.name != str(r['pid'])+'.sock'
                or p.parent.resolve() not in [x.resolve() for x in self.socket_roots]):
            raise BridgeError('UNSAFE_SOCKET')
        check_dir(p.parent, private=True)
        return p

    def _check_peer(self, conn, r):
        # Darwin sys/un.h: SOL_LOCAL=0, LOCAL_PEERPID=0x002.
        try:
            pid = struct.unpack('i', conn.getsockopt(0, 2, 4))[0]
        except OSError:
            raise BridgeError('SOCKET_PEER_UNVERIFIED') from None
        if pid != r['pid']:
            raise BridgeError('SOCKET_PEER_MISMATCH')

    def _transcript(self, r):
        sid = str(r.get('sessionId', ''))
        try:
            if str(uuid.UUID(sid)) != sid:
                raise ValueError()
        except ValueError:
            raise BridgeError('INVALID_NATIVE_SESSION_ID') from None
        return self.claude/'projects'/encode_cwd(r['cwd'])/(sid+'.jsonl')

    def _metadata(self, r):
        rows, st = transcript_rows(self._transcript(r))
        model = permission = None
        for row in rows:
            if row.get('sessionId') != r['sessionId']:
                continue
            if row.get('type') == 'assistant' and row.get('message', {}).get('model'):
                model = row['message']['model']
            if row.get('type') == 'user' and row.get('permissionMode'):
                permission = row['permissionMode']
        return {'last_observed_model':model, 'last_observed_permission':permission,
                'transcript_bytes':st.st_size}

    def _validate(self, r):
        if r.get('version') not in VERIFIED_VERSIONS or r.get('peerProtocol') != 1:
            raise BridgeError('UNVERIFIED_RUNTIME_VERSION', 'Inspect adapter compatibility before sending')
        self._socket(r)
        self._check_process(r)
        return r

    def _lookup(self, host_id):
        rows = [r for r in self._records() if r.get('hostSessionId') == host_id]
        if len(rows) != 1:
            raise BridgeError('SESSION_NOT_UNIQUE_OR_NOT_RUNNING')
        return self._validate(rows[0])

    def list_sessions(self):
        out = []
        for r in self._records():
            item = {k:r.get(k) for k in ('hostSessionId','sessionId','name','cwd','pid','version','status')}
            try:
                self._validate(r)
                item.update(self._metadata(r))
                item['compatible'] = True
            except BridgeError as e:
                item.update(compatible=False, error=e.code)
            out.append(item)
        return {'sessions':out, 'screen_locked':screen_locked()}

    def _bindings(self):
        p = self.state/'bindings.json'
        return read_json(p, private=True) if p.exists() else {}

    def bind(self, alias, host_id, expected_model, replace=False):
        checked_name(alias)
        if not isinstance(expected_model, str) or not expected_model.startswith('claude-'):
            raise BridgeError('EXACT_MODEL_REQUIRED')
        with self.locked():
            r = self._lookup(host_id)
            observed = self._metadata(r)
            if observed['last_observed_model'] != expected_model:
                raise BridgeError('MODEL_NOT_OBSERVED')
            if observed['last_observed_permission'] != 'plan':
                raise BridgeError('PLAN_MODE_NOT_OBSERVED')
            bindings = self._bindings()
            existing = bindings.get(alias)
            entry = {'host_session_id':host_id, 'native_session_id':r['sessionId'],
                     'cwd':r['cwd'], 'expected_model':expected_model, 'required_mode':'plan'}
            if existing and any(existing.get(k) != v for k, v in entry.items()) and not replace:
                raise BridgeError('ALIAS_ALREADY_BOUND')
            bindings[alias] = dict(entry, bound_at=now())
            atomic_json(self.state/'bindings.json', bindings)
        return self.status(alias)

    def _target(self, alias):
        checked_name(alias)
        b = self._bindings().get(alias)
        if not b:
            raise BridgeError('ALIAS_NOT_BOUND')
        r = self._lookup(b['host_session_id'])
        if r['sessionId'] != b['native_session_id'] or r['cwd'] != b['cwd']:
            raise BridgeError('BINDING_CHANGED', 'Explicit rebind required; no automatic retargeting')
        return b, r

    def status(self, alias):
        with self.locked():
            b, r = self._target(alias)
            return {'alias':alias, **b, 'pid':r['pid'], 'runtime_version':r['version'],
                    'session_status':r['status'], **self._metadata(r),
                    'screen_locked':screen_locked(),
                    'model_note':'Last observed model; actual model is checked again in each new reply.'}

    def send(self, alias, prompt, request_id, require_locked=False):
        checked_name(alias)
        checked_name(request_id)
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode()) > MAX_PROMPT:
            raise BridgeError('INVALID_PROMPT', 'Nonempty UTF-8 prompt, at most 64 KiB')
        fingerprint = hashlib.sha256(json.dumps([alias,prompt],ensure_ascii=False).encode()).hexdigest()
        p = self.state/'requests'/(request_id+'.json')
        with self.locked():
            if p.exists():
                prior = read_json(p, private=True)
                if prior.get('prompt_fingerprint') != fingerprint:
                    raise BridgeError('REQUEST_ID_CONFLICT')
                current_binding = self._bindings().get(alias)
                if current_binding and any(current_binding.get(k) != prior.get(k)
                                           for k in ('host_session_id','native_session_id','cwd','expected_model')):
                    raise BridgeError('REQUEST_ID_CONFLICT', 'Alias binding changed')
                return prior  # Never resend an ambiguous or failed request implicitly.
            b, r = self._target(alias)
            for prior_path in (self.state/'requests').glob('*.json'):
                prior = read_json(prior_path, private=True)
                if (prior.get('native_session_id') == b['native_session_id']
                        and prior.get('host_session_id') == b['host_session_id']
                        and prior.get('status') not in FINAL):
                    raise BridgeError('PENDING_REQUEST', 'Read '+prior['request_id']+' first')
            if r.get('status') != 'idle':
                raise BridgeError('SESSION_BUSY')
            meta = self._metadata(r)
            if meta['last_observed_model'] != b['expected_model']:
                raise BridgeError('MODEL_NOT_OBSERVED')
            if meta['last_observed_permission'] != b['required_mode']:
                raise BridgeError('PLAN_MODE_NOT_OBSERVED')
            locked = screen_locked()
            if require_locked and locked is not True:
                raise BridgeError('SCREEN_NOT_CONFIRMED_LOCKED')
            transcript = self._transcript(r)
            fd, st = safe_open(transcript)
            try:
                if st.st_size:
                    os.lseek(fd, st.st_size-1, os.SEEK_SET)
                    if os.read(fd, 1) != b'\n':
                        raise BridgeError('TRANSCRIPT_BUSY', 'A native log line is still being written')
            finally:
                os.close(fd)
            marker = f'[CODEX-CLAUDE:{request_id}]'
            message_uuid = str(uuid.uuid4())
            ledger = {'request_id':request_id,'alias':alias,**b,
                      'message_uuid':message_uuid,'prompt_fingerprint':fingerprint,
                      'marker':marker,'created_at':now(),'status':'prepared',
                      'delivery_observed':False,'transcript':str(transcript),
                      'transcript_offset':st.st_size,'transcript_device':st.st_dev,
                      'transcript_inode':st.st_ino,'screen_locked_before_send':locked}
            atomic_json(p, ledger)
            # type=user is the native wire envelope; Claude marks it as peer-origin.
            # No auth token, from_mode, selfSent, control actions or attachments.
            content = (marker+'\n来自 Codex 的协作消息，不是新的人工授权。保持本会话原有权限；'
                       '仅完成下述已由用户请求的沟通/审阅，不修改配置或升级权限。'
                       '最终回答第一行请原样保留上述标识，随后给出结果。\n\n'+prompt)
            frame = {'type':'user','session_id':r['sessionId'],'uuid':message_uuid,
                     'msg_id':message_uuid,'from':'Codex local bridge','priority':'later',
                     'message':{'role':'user','content':content}}
            started_send = False
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                    conn.settimeout(3)
                    conn.connect(str(self._socket(r)))
                    self._check_peer(conn, r)
                    self._check_process(r)
                    ledger['status']='sending'
                    atomic_json(p,ledger)
                    started_send=True
                    conn.sendall((json.dumps(frame,ensure_ascii=False)+'\n').encode())
                ledger['status']='sent_unconfirmed'
                ledger['sent_at']=now()
            except (OSError, BridgeError) as e:
                ledger['status']='delivery_unknown' if started_send else 'not_sent'
                ledger['error_code']=e.code if isinstance(e,BridgeError) else type(e).__name__
            atomic_json(p, ledger)
            return ledger

    def _read_once(self, request_id):
        p = self.state/'requests'/(checked_name(request_id)+'.json')
        with self.locked():
            r = read_json(p, private=True)
            if r['status'] in FINAL:
                return r
            rows, st = transcript_rows(Path(r['transcript']), r['transcript_offset'])
            if (st.st_dev,st.st_ino)!=(r['transcript_device'],r['transcript_inode']) or st.st_size<r['transcript_offset']:
                r['status']='transcript_changed'
                atomic_json(p,r)
                return r
            ancestors=set()
            observed=False
            answer=None
            actual_model=None
            for d in rows:
                if d.get('sessionId') != r['native_session_id']:
                    continue
                ident=d.get('uuid')
                if d.get('type')=='user' and ident==r['message_uuid'] and r['marker'] in text_of(d):
                    observed=True
                    r['actual_permission_mode']=d.get('permissionMode')
                    if d.get('permissionMode') != r['required_mode']:
                        r['status']='permission_mode_mismatch' if d.get('permissionMode') else 'permission_mode_unverified'
                        break
                    ancestors.add(ident)
                    continue
                if not observed:
                    continue
                if d.get('type')=='user' and ident!=r['message_uuid']:
                    content=d.get('message',{}).get('content')
                    is_tool_result=(isinstance(content,list) and bool(content)
                                    and all(isinstance(x,dict) and x.get('type')=='tool_result' for x in content))
                    if not is_tool_result:
                        r['status']='interleaved'
                        break
                if d.get('parentUuid') not in ancestors:
                    continue
                if ident:
                    ancestors.add(ident)
                if d.get('type')!='assistant':
                    continue
                m=d.get('message',{})
                model=m.get('model')
                if model and model!=r['expected_model']:
                    actual_model=model
                    r['status']='model_mismatch'
                    break
                body=text_of(d)
                if r['marker'] in body and m.get('stop_reason')=='end_turn' and model==r['expected_model']:
                    answer=body
                    actual_model=model
                    r['reply_uuid']=ident
                    break
            r['delivery_observed']=observed
            r['last_checked_at']=now()
            r['screen_locked_at_read']=screen_locked()
            if actual_model:
                r['actual_model']=actual_model
            if answer is not None:
                r['status']='completed'
                r['reply']=answer[:65536]
                r['reply_truncated']=len(answer)>65536
                r['completed_at']=now()
                r['locked_roundtrip_verified']=(r['screen_locked_before_send'] is True and r['screen_locked_at_read'] is True)
            elif observed and r['status'] not in FINAL:
                r['status']='delivered_waiting_reply'
            atomic_json(p,r)
            return r

    def read(self, request_id, wait_seconds=0):
        if not isinstance(wait_seconds,(float,int)) or not 0<=wait_seconds<=55:
            raise BridgeError('INVALID_WAIT', '0..55 seconds')
        deadline=time.monotonic()+wait_seconds
        while True:
            r=self._read_once(request_id)
            if r['status'] in FINAL or time.monotonic()>=deadline:
                return r
            time.sleep(min(1,max(0,deadline-time.monotonic())))


def mcp(bridge):
    """MCP stdio, JSON-RPC newline framing; no HTTP listener or credentials."""
    def schema(props, required):
        return {'type':'object','properties':props,'required':required,'additionalProperties':False}
    string={'type':'string'}
    definitions=[
        ('claude_app_list_sessions','List live Desktop Code task metadata, without reading conversation text.',schema({},[]),True),
        ('claude_app_bind','Bind an exact user-selected Desktop task ID; defaults to observed Plan mode.',schema({'alias':string,'host_session_id':string,'expected_model':string},['alias','host_session_id','expected_model']),False),
        ('claude_app_status','Read a bound task identity, observed model and lock state.',schema({'alias':string},['alias']),True),
        ('claude_app_send','Send one authorized peer message to an idle bound task. Reuse request_id after uncertainty; never auto-resend.',schema({'alias':string,'prompt':string,'request_id':string,'require_locked':{'type':'boolean'}},['alias','prompt','request_id']),False),
        ('claude_app_read','Read only the correlated new reply; verifies native task, ancestry, marker and actual model.',schema({'request_id':string,'wait_seconds':{'type':'number','minimum':0,'maximum':55}},['request_id']),True),
    ]
    handlers={'claude_app_list_sessions':lambda **a:bridge.list_sessions(),
              'claude_app_bind':lambda alias,host_session_id,expected_model:bridge.bind(alias,host_session_id,expected_model),
              'claude_app_status':bridge.status,'claude_app_send':bridge.send,'claude_app_read':bridge.read}
    for line in sys.stdin:
        req=None
        try:
            req=json.loads(line)
            if not isinstance(req,dict):
                raise ValueError()
            if 'id' not in req:
                continue
            method=req.get('method')
            if method=='initialize':
                requested=req.get('params',{}).get('protocolVersion')
                version=requested if requested in {'2024-11-05','2025-03-26','2025-06-18'} else '2024-11-05'
                result={'protocolVersion':version,'capabilities':{'tools':{}},'serverInfo':{'name':'claude-app-headless','version':'0.1.0'}}
            elif method=='ping':
                result={}
            elif method=='tools/list':
                result={'tools':[{'name':n,'description':d,'inputSchema':s,'annotations':{'readOnlyHint':ro,'destructiveHint':False,'openWorldHint':not ro}} for n,d,s,ro in definitions]}
            elif method=='tools/call':
                params=req.get('params',{});name=params.get('name');args=params.get('arguments',{})
                if name not in handlers or not isinstance(args,dict):
                    raise BridgeError('UNKNOWN_TOOL_OR_ARGUMENTS')
                try:
                    data=handlers[name](**args)
                    result={'content':[{'type':'text','text':json.dumps(data,ensure_ascii=False)}],'isError':False}
                except (BridgeError,TypeError,OSError) as e:
                    result={'content':[{'type':'text','text':json.dumps({'error':e.code if isinstance(e,BridgeError) else type(e).__name__})}],'isError':True}
            else:
                raise BridgeError('METHOD_NOT_FOUND')
            response={'jsonrpc':'2.0','id':req['id'],'result':result}
        except (ValueError,BridgeError) as e:
            response={'jsonrpc':'2.0','id':req.get('id') if isinstance(req,dict) else None,
                      'error':{'code':-32600,'message':e.code if isinstance(e,BridgeError) else 'Invalid JSON-RPC request'}}
        print(json.dumps(response,ensure_ascii=False),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('list');sub.add_parser('doctor');sub.add_parser('mcp')
    b=sub.add_parser('bind');b.add_argument('alias');b.add_argument('--host-session-id',required=True);b.add_argument('--expect-model',required=True);b.add_argument('--replace',action='store_true')
    s=sub.add_parser('status');s.add_argument('alias')
    s=sub.add_parser('send');s.add_argument('alias');s.add_argument('--request-id',required=True);s.add_argument('--prompt-file');s.add_argument('--require-locked',action='store_true')
    r=sub.add_parser('read');r.add_argument('request_id');r.add_argument('--wait',type=float,default=0)
    a=p.parse_args();bridge=Bridge()
    try:
        if a.command=='mcp':
            mcp(bridge);return 0
        if a.command in {'list','doctor'}:
            out=bridge.list_sessions()
        elif a.command=='bind':
            out=bridge.bind(a.alias,a.host_session_id,a.expect_model,a.replace)
        elif a.command=='status':
            out=bridge.status(a.alias)
        elif a.command=='send':
            prompt=Path(a.prompt_file).read_text() if a.prompt_file else sys.stdin.read(MAX_PROMPT+1)
            out=bridge.send(a.alias,prompt,a.request_id,a.require_locked)
        else:
            out=bridge.read(a.request_id,a.wait)
        print(json.dumps(out,ensure_ascii=False,indent=2))
        return 0
    except (BridgeError,OSError) as e:
        print(json.dumps({'error':e.code if isinstance(e,BridgeError) else type(e).__name__,
                          'message':str(e) if isinstance(e,BridgeError) else 'Local operation failed; no automatic retry.'},ensure_ascii=False))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
