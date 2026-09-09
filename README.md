# AI Coding Skills

面向 vibe coding 的轻量维护工作流：需求有验收、代码有入口、修改有测试、协作有交接。
不需要向量数据库、在线服务或额外模型调用。规则跨语言；附带索引器仅解析 Python。

## 30 秒看懂

它帮助 AI 把「不停翻代码」变成「找到入口和调用方 → 复现一个问题 → 做一个小补丁 → 留下可继续的交接」。核心是技能与模板，索引器是可选助手，不是比 rg/LSP 更快的既定结论。

例如排查 `snapshot`：
- Before：重复读取函数正文，再全仓搜索引用，下一次会话重新开始。
- After：`query snapshot --callers --rebuild` 列出候选调用方位置，写一个失败测试，修复后把证据和下一步留在交接中。

这是使用方式示例，不是已测得的性能提升。README/立项说明用中文方便维护者阅读，技能和模板刻意使用英文方便不同 AI 客户端复用。

## 使用

将 `skills/efficient-code-maintenance/` 作为技能目录提供给支持 SKILL.md 的 AI 客户端。
不同客户端的技能安装路径不同，本项目不自动修改全局配置。也可直接让 AI 阅读其 SKILL.md。

新项目可说：
> 阅读 skills/efficient-code-maintenance/SKILL.md，按我的需求立项，使用技能目录内的 templates 建立维护入口；不要覆盖已有文件，不要自动部署。

已有项目可说：
> 使用 efficient-code-maintenance，先定位并复现这个问题，然后提交最小修复和验证证据，不重扫无关代码。

复制模板时把占位项替换成真实项目内容；已有 AGENTS.md 必须合并，不覆盖。
维护需求只保留单一事实源；如果已有 issue tracker，PROJECT.md 只链接它。

## Python 索引

```sh
python skills/efficient-code-maintenance/scripts/code_index.py build --root /path/to/repo
python skills/efficient-code-maintenance/scripts/code_index.py check --root /path/to/repo
python skills/efficient-code-maintenance/scripts/code_index.py query chat_completions --root /path/to/repo
python skills/efficient-code-maintenance/scripts/code_index.py query snapshot --callers --rebuild --root /path/to/repo
python -m unittest discover -s tests
```

要求 Python 3.9+ 和 Git。Mac/Linux/Windows 可用同一 Python 脚本。
只读 Git 跟踪的 .py 文件，不导入业务模块，不索引默认参数、正文、docstring。
索引包含符号名和路径，仍可能泄露业务结构，应留在本地并忽略 `.code-index/`。
默认排除 vendor、node_modules、__pycache__ 和隐藏目录。业务目录由重复的 `--exclude static --exclude private_media` 自行配置，每次调用使用相同选项。
`query --rebuild` 自动刷新过期/缺失索引，未指定时保留严格检查；构建失败不使用旧数据。错误显示安全的文件名和行号，不输出源代码片段或 Git stderr。
非 Python 使用 rg/LSP；不假装支持其 AST。反向查询是按调用名称的候选关系，可能包含同名误匹配与嵌套作用域调用。
新未跟踪文件需直接检查；先确认无敏感信息再决定是否加入 Git。

## 交付边界

索引不是完整调用图，测试通过不等于生产验收。没有可靠的实测 token 基线前，不承诺节省百分比。
此仓库不包含任何业务凭证、账号、生产日志或 ai2api 业务源码。
项目计划与验收见 PROJECT.md。

许可证：MIT，见 LICENSE。单独复制技能时，保留技能内的 LICENSE 即可。
