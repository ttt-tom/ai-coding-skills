"""Author-written isolated tests. No Claude process or model is started."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).with_name('claude_app_headless.py')
if SOURCE.exists():
    spec = importlib.util.spec_from_file_location('headless', SOURCE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
else:
    mod = None


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(mod, 'headless bridge implementation is missing')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.claude = self.root/'claude'
        self.sessions = self.claude/'sessions'
        self.sessions.mkdir(parents=True, mode=0o700)
        self.sockdir = self.root/'socks'
        self.sockdir.mkdir(mode=0o700)
        self.sockpath = self.sockdir/'123456.sock'
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(self.sockpath))
        self.sockpath.chmod(0o600)
        self.server.listen(4)
        self.server.settimeout(.2)
        self.addCleanup(self.server.close)
        self.cwd = str(self.root/'project')
        self.sid = '00000000-0000-4000-8000-000000000001'
        self.hostid = 'local_test_exact_app_task'
        self.record = {'pid':123456, 'sessionId':self.sid, 'hostSessionId':self.hostid,
                       'cwd':self.cwd, 'name':'Review task', 'version':'2.1.299',
                       'entrypoint':'claude-desktop', 'peerProtocol':1,
                       'procStart':'fixture-start', 'status':'idle',
                       'messagingSocketPath':str(self.sockpath)}
        self.record_path = self.sessions/'123456.json'
        self.record_path.write_text(json.dumps(self.record))
        self.transcript = self.claude/'projects'/mod.encode_cwd(self.cwd)/(self.sid+'.jsonl')
        self.transcript.parent.mkdir(parents=True)
        self.append({'type':'user','uuid':'previous-user','sessionId':self.sid,
                     'permissionMode':'plan','message':{'content':'prior'}})
        self.append({'type':'assistant','uuid':'previous-answer','parentUuid':'previous-user',
                     'sessionId':self.sid,'message':{'model':'claude-fable-5-1',
                     'stop_reason':'end_turn','content':[{'type':'text','text':'old answer'}]}})
        self.bridge = mod.Bridge(self.claude, self.root/'state')
        self.bridge.socket_roots = [self.sockdir]
        self.bridge._check_process = lambda record: None
        self.bridge._check_peer = lambda connection, record: None
        self.bridge.bind('fable',self.hostid,'claude-fable-5-1')

    def append(self, record):
        with self.transcript.open('a') as f:
            f.write(json.dumps(record)+'\n')

    def receive(self):
        conn,_ = self.server.accept()
        with conn:
            data=b''
            while not data.endswith(b'\n'):
                data+=conn.recv(4096)
        return json.loads(data)

    def reply(self, frame, model='claude-fable-5-1', content=None, parent=None):
        self.append({'type':'user','uuid':frame['uuid'],'sessionId':self.sid,
                     'permissionMode':'plan','message':frame['message']})
        self.append({'type':'assistant','uuid':'reply-'+frame['uuid'],
                     'parentUuid':parent or frame['uuid'],'sessionId':self.sid,
                     'message':{'model':model,'stop_reason':'end_turn',
                                'content':[{'type':'text','text':content or frame['message']['content'].splitlines()[0]+' OK'}]}})

    def test_round_trip_exact_task_model_and_non_privileged_frame(self):
        sent=self.bridge.send('fable','Return only OK','r-one')
        frame=self.receive()
        self.assertEqual(frame['session_id'],self.sid)
        self.assertEqual(frame['type'],'user')
        self.assertNotIn('from_mode',frame)
        self.assertNotIn('token',frame)
        self.assertNotIn('action',frame)
        self.assertEqual(sent['status'],'sent_unconfirmed')
        self.reply(frame)
        result=self.bridge.read('r-one')
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['actual_model'],'claude-fable-5-1')
        self.assertTrue(result['delivery_observed'])

    def test_same_request_is_not_replayed_after_restart(self):
        self.bridge.send('fable','same','r-repeat');self.receive()
        other=mod.Bridge(self.claude,self.root/'state')
        replay=other.send('fable','same','r-repeat')
        self.assertEqual(replay['status'],'sent_unconfirmed')
        with self.assertRaises(socket.timeout):self.server.accept()
        with self.assertRaisesRegex(mod.BridgeError,'REQUEST_ID_CONFLICT'):
            other.send('fable','changed','r-repeat')

    def test_unknown_send_never_claims_delivery_or_replays(self):
        self.bridge.send('fable','test','r-unknown');self.receive()
        result=self.bridge.read('r-unknown')
        self.assertEqual(result['status'],'sent_unconfirmed')
        self.assertFalse(result['delivery_observed'])
        self.bridge.send('fable','test','r-unknown')
        with self.assertRaises(socket.timeout):self.server.accept()

    def test_wrong_model_is_not_fable_success(self):
        self.bridge.send('fable','test','r-model');frame=self.receive()
        self.reply(frame,model='other-model')
        self.assertEqual(self.bridge.read('r-model')['status'],'model_mismatch')

    def test_unrelated_reply_with_marker_cannot_complete(self):
        self.bridge.send('fable','test','r-parent');frame=self.receive()
        self.reply(frame,parent='unrelated-parent')
        self.assertNotEqual(self.bridge.read('r-parent')['status'],'completed')

    def test_interleaved_user_turn_is_ambiguous(self):
        self.bridge.send('fable','test','r-interleave');frame=self.receive()
        self.append({'type':'user','uuid':frame['uuid'],'sessionId':self.sid,'permissionMode':'plan','message':frame['message']})
        self.append({'type':'user','uuid':'human-other','parentUuid':frame['uuid'],
                     'sessionId':self.sid,'message':{'content':'separate human task'}})
        self.append({'type':'assistant','uuid':'last','parentUuid':'human-other','sessionId':self.sid,
                     'message':{'model':'claude-fable-5-1','stop_reason':'end_turn',
                     'content':[{'type':'text','text':'[CODEX-CLAUDE:r-interleave] OK'}]}})
        self.assertEqual(self.bridge.read('r-interleave')['status'],'interleaved')

    def test_busy_target_is_not_interrupted(self):
        self.record['status']='busy';self.record_path.write_text(json.dumps(self.record))
        with self.assertRaisesRegex(mod.BridgeError,'SESSION_BUSY'):
            self.bridge.send('fable','test','r-busy')
        with self.assertRaises(socket.timeout):self.server.accept()

    def test_changed_native_session_does_not_retarget_alias(self):
        self.record['sessionId']='00000000-0000-4000-8000-000000000002'
        self.record_path.write_text(json.dumps(self.record))
        with self.assertRaisesRegex(mod.BridgeError,'BINDING_CHANGED'):
            self.bridge.send('fable','test','r-drift')

    def test_group_writable_metadata_and_symlink_socket_rejected(self):
        self.record_path.chmod(0o666)
        with self.assertRaisesRegex(mod.BridgeError,'UNSAFE_FILE'):
            self.bridge.status('fable')
        self.record_path.chmod(0o600)
        alias=self.sockdir/'alias.sock';alias.symlink_to(self.sockpath)
        self.record['messagingSocketPath']=str(alias);self.record_path.write_text(json.dumps(self.record))
        with self.assertRaisesRegex(mod.BridgeError,'UNSAFE_SOCKET'):
            self.bridge.status('fable')

    def test_private_state_does_not_store_prompt(self):
        self.bridge.send('fable','private prompt text','r-private');self.receive()
        p=self.root/'state'/'requests'/'r-private.json'
        self.assertEqual(p.stat().st_mode & 0o777,0o600)
        self.assertNotIn('private prompt text',p.read_text())

    def test_transcript_replacement_does_not_reuse_offset(self):
        self.bridge.send('fable','test','r-rotated');self.receive()
        replacement=self.transcript.with_suffix('.new');replacement.write_text('{}\n')
        replacement.replace(self.transcript)
        self.assertEqual(self.bridge.read('r-rotated')['status'],'transcript_changed')

    def test_image_only_human_input_is_interleaved(self):
        self.bridge.send('fable','test','r-image');frame=self.receive()
        self.append({'type':'user','uuid':frame['uuid'],'sessionId':self.sid,
                     'permissionMode':'plan','message':frame['message']})
        self.append({'type':'user','uuid':'human-image','parentUuid':frame['uuid'],
                     'sessionId':self.sid,'message':{'content':[{'type':'image','source':{'type':'base64','data':'fixture'}}]}})
        self.append({'type':'assistant','uuid':'image-answer','parentUuid':'human-image','sessionId':self.sid,
                     'message':{'model':'claude-fable-5-1','stop_reason':'end_turn',
                                'content':[{'type':'text','text':'[CODEX-CLAUDE:r-image] answer-human-image'}]}})
        self.assertEqual(self.bridge.read('r-image')['status'],'interleaved')

    def test_new_inbound_mode_drift_is_reported(self):
        self.bridge.send('fable','test','r-mode');frame=self.receive()
        self.append({'type':'user','uuid':frame['uuid'],'sessionId':self.sid,
                     'permissionMode':'bypassPermissions','message':frame['message']})
        self.append({'type':'assistant','uuid':'mode-answer','parentUuid':frame['uuid'],'sessionId':self.sid,
                     'message':{'model':'claude-fable-5-1','stop_reason':'end_turn',
                     'content':[{'type':'text','text':'[CODEX-CLAUDE:r-mode] OK'}]}})
        self.assertEqual(self.bridge.read('r-mode')['status'],'permission_mode_mismatch')

    def test_partial_transcript_line_blocks_before_send(self):
        with self.transcript.open('ab') as f:f.write(b'{"type":"system"')
        with self.assertRaisesRegex(mod.BridgeError,'TRANSCRIPT_BUSY'):
            self.bridge.send('fable','test','r-partial-line')
        with self.assertRaises(socket.timeout):self.server.accept()
        self.assertFalse((self.root/'state/requests/r-partial-line.json').exists())

    def test_different_id_cannot_overlap_unconfirmed_request(self):
        self.bridge.send('fable','first','r-pending');self.receive()
        with self.assertRaisesRegex(mod.BridgeError,'PENDING_REQUEST'):
            self.bridge.send('fable','second','r-second')
        with self.assertRaises(socket.timeout):self.server.accept()

    def test_rebound_alias_does_not_return_old_target_as_new_send(self):
        self.bridge.send('fable','same','r-rebound');self.receive()
        p=self.root/'state/bindings.json';b=json.loads(p.read_text())
        b['fable']['host_session_id']='local_other_task';p.write_text(json.dumps(b))
        with self.assertRaisesRegex(mod.BridgeError,'REQUEST_ID_CONFLICT'):
            self.bridge.send('fable','same','r-rebound')

    def test_require_locked_rejects_unlocked_before_transmission(self):
        with patch.object(mod,'screen_locked',return_value=False):
            with self.assertRaisesRegex(mod.BridgeError,'SCREEN_NOT_CONFIRMED_LOCKED'):
                self.bridge.send('fable','test','r-lock',require_locked=True)
        with self.assertRaises(socket.timeout):self.server.accept()


if __name__=='__main__':
    unittest.main()
