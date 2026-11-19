# 测试脚本

所有 `_test_*.py` 回归用例、`_smoke_*` / `_spike_*` 冒烟与验证脚本、`_gen_icon.py` 工具。
运行方式（在工作区根目录执行）：

```
./.venv/Scripts/python.exe -X utf8 测试脚本/_test_lyric_rules.py
```

脚本内的路径已适配本目录（自动向上一级找工作区资源），移动后无需再改。
