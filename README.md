# OpenClaw + AutoGLM Phone Agent 搭建 SOP

## 概述

搭建 OpenClaw → AutoGLM Phone Agent → 真实手机（ADB）架构，实现通过自然语言控制手机 UI 操作。

## 架构图

```
OpenClaw (调度中心)
    ↓ HTTP POST /run
AutoGLM Service (FastAPI, 127.0.0.1:9001)
    ↓ python main.py
llama-server (VLM, 127.0.0.1:8081)
    ↓ ADB commands
Android Device (192.168.1.15:41937)
```

## 强制技术约束

1. ❌ 禁止使用 Ollama 作为 Phone-VLM（仅允许 llama.cpp）
2. ✅ 必须加载 AutoGLM-Phone-9B + 对应量化等级的 mmproj
3. ✅ llama-server 仅监听 127.0.0.1
4. ✅ AutoGLM 必须被封装为 HTTP 服务（/run）
5. ❌ OpenClaw 不允许直接调用 adb

## 环境配置

- **OS**: macOS
- **Python**: 3.11
- **模型目录**: ~/models/autoglm
- **代码目录**: ~/code
- **llama-server 端口**: 8081
- **AutoGLM Service 端口**: 9001
- **模型量化**: Q4_K_M
- **模型名**: autoglm-phone-9b

---

## Step 1：安装依赖

```bash
# 安装 android-platform-tools（adb）
brew install android-platform-tools

# 安装 python@3.11
brew install python@3.11

# 安装 llama.cpp（包含 llama-server）
brew install llama.cpp

# 验证安装
adb version          # 应显示 1.0.41+
python3.11 --version # 应显示 3.11.14+
llama-server --version  # 应显示 7880+
```

---

## Step 2：准备模型

确保以下文件存在于 `~/models/autoglm`：

```
~/models/autoglm/
├── AutoGLM-Phone-9B-Q4_K_M.gguf      # 主模型 (~5.7G)
└── AutoGLM-Phone-9B-mmproj.gguf      # mmproj 模型 (~1.7G)
```

> 下载链接：从官方或 HuggingFace 获取对应模型

---

## Step 3：启动 llama-server（VLM）

```bash
cd ~/models/autoglm

llama-server \
  --model AutoGLM-Phone-9B-Q4_K_M.gguf \
  --mmproj AutoGLM-Phone-9B-mmproj.gguf \
  --ctx-size 16384 \
  --host 127.0.0.1 \
  --port 8081 \
  --alias autoglm-phone-9b
```

> 注意：不要使用 `--log-format` 参数（某些版本不支持）

### 验证

```bash
curl http://127.0.0.1:8081/v1/models
```

应返回包含 `autoglm-phone-9b` 的模型列表。

---

## Step 4：部署 Open-AutoGLM

```bash
cd ~/code

# Clone 仓库（如已存在则跳过）
git clone https://github.com/zai-org/Open-AutoGLM.git
cd Open-AutoGLM

# 创建 Python 3.11 venv
python3.11 -m venv venv

# 安装依赖
./venv/bin/pip install -e .

# 安装 httpx SOCKS 支持（重要！）
./venv/bin/pip install 'httpx[socks]'
```

---

## Step 5：封装 AutoGLM 为 HTTP Service

创建 `autoglm_service.py`：

```python
#!/usr/bin/env python3
"""
AutoGLM HTTP Service
暴露 /run 接口供 OpenClaw 调用
"""
import subprocess
import time
import os
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import uvicorn

app = FastAPI(title="AutoGLM Phone Agent Service")

# 强制只使用局域网设备（根据实际情况修改）
os.environ["ANDROID_SERIAL"] = "192.168.1.15:41937"


class RunRequest(BaseModel):
    instruction: str


class RunResponse(BaseModel):
    success: bool
    stdout_tail: Optional[str] = None
    stderr_tail: Optional[str] = None
    duration: float


@app.post("/run", response_model=RunResponse)
async def run_agent(request: RunRequest):
    """
    执行 AutoGLM Phone Agent

    Args:
        instruction: 自然语言手机操作指令

    Returns:
        success: 是否成功
        stdout_tail: 标准输出（末尾部分）
        stderr_tail: 标准输出（末尾部分）
        duration: 执行耗时（秒）
    """
    start_time = time.time()

    cmd = [
        "./venv/bin/python",
        "main.py",
        "--base-url", "http://127.0.0.1:8081/v1",
        "--model", "autoglm-phone-9b",
        request.instruction
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5分钟超时
            cwd="/Users/anshi/code/Open-AutoGLM",
            env=os.environ.copy()
        )

        duration = time.time() - start_time
        success = result.returncode == 0

        return RunResponse(
            success=success,
            stdout_tail=result.stdout[-2000:] if result.stdout else None,
            stderr_tail=result.stderr[-2000:] if result.stderr else None,
            duration=duration
        )

    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        return RunResponse(
            success=False,
            stderr_tail="Command timed out after 300 seconds",
            duration=duration
        )
    except Exception as e:
        duration = time.time() - start_time
        return RunResponse(
            success=False,
            stderr_tail=str(e),
            duration=duration
        )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "AutoGLM Phone Agent"}


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=9001,
        log_level="info"
    )
```

安装 FastAPI 和 uvicorn：

```bash
./venv/bin/pip install fastapi uvicorn
```

---

## Step 6：启动 AutoGLM Service

```bash
cd ~/code/Open-AutoGLM
./venv/bin/python autoglm_service.py
```

### 验证

```bash
# 健康检查
curl http://127.0.0.1:9001/health

# 访问 API 文档
open http://127.0.0.1:9001/docs
```

---

## Step 7：ADB 验证

```bash
# 查看连接的设备
adb devices -l

# 应显示类似：
# List of devices attached
# 192.168.1.15:41937     device product:LSA-AN00 model:LSA_AN00
```

如果设备显示 `unauthorized`，需要在手机上点击"允许 USB 调试"。

---

## Step 8：端到端验证

```bash
curl -X POST http://127.0.0.1:9001/run \
  -H "Content-Type: application/json" \
  -d '{"instruction": "回到桌面并打开系统设置"}'
```

### 成功标准

- 接口返回 `success=true`
- 手机界面发生真实变化（打开设置应用）

---

## 最终服务配置

### llama-server
- **base_url**: http://127.0.0.1:8081/v1
- **model**: autoglm-phone-9b

### AutoGLM Service
- **endpoint**: POST http://127.0.0.1:9001/run
- **body**:
  ```json
  {
    "instruction": "自然语言手机操作"
  }
  ```

---

## OpenClaw Tool 定义（建议）

```yaml
tool_name: phone_agent
description: "通过自然语言控制手机 UI 操作"
parameters:
  instruction:
    type: string
    description: "自然语言指令，如：打开微信、回到桌面、切换到设置等"
execution:
  method: POST
  url: http://127.0.0.1:9001/run
  body_template: |
    {"instruction": "{{instruction}}"}
rules:
  - 所有涉及手机 UI 的任务必须调用该 tool
  - 禁止直接使用 adb 命令
```

---

## AgentSkills 集成

本仓库提供三个 OpenClaw AgentSkills，用于构建完整的手机自动化闭环：

### 技能列表

| 技能 | 作用 | 状态改变 | 说明 |
|------|------|---------|------|
| `phone-observe` | 观察屏幕状态 | ❌ 不改变 | 仅读取当前屏幕状态（弹窗、元素、文本） |
| `phone-plan` | 规划下一步操作 | ❌ 不改变 | 根据目标和状态生成一条操作指令 |
| `phone-control` | 执行操作 | ✅ 改变 | 通过 AutoGLM 执行自然语言指令 |
| `phone-loop` | 串行自动化闭环 | ✅ 改变 | 自动化执行 observe → plan → act → observe |

### 技能文件

所有技能文件位于 `skills/` 目录：

- `phone-observe.skill` - 观察技能
- `phone-plan.skill` - 规划技能
- `phone-control.skill` - 控制技能
- `phone-loop.skill` - 闭环技能

### 安装技能

将 `.skill` 文件复制到 OpenClaw 的 skills 目录，重启 OpenClaw 即可加载。

```bash
# 复制技能到 OpenClaw
cp skills/*.skill /opt/homebrew/lib/node_modules/openclaw/skills/public/

# 重启 OpenClaw（如果需要）
openclaw gateway restart
```

### 使用方式

#### 1. 单步操作

直接使用 `phone-control` 执行单个操作：

```
/phone-control 打开微信
```

#### 2. 规划与执行

先观察，再规划，最后执行：

```
/phone-observe
/phone-plan 给张三发消息 <观察结果JSON>
/phone-control <规划结果>
```

#### 3. 自动化闭环

使用 `phone-loop` 自动完成多步任务：

```
/phone-loop 目标：打开微信进入聊天列表；轮次：3
```

#### 4. JSON 输入（phone-loop）

```json
/phone-loop {
  "goal": "在微信中搜索张三并打开聊天",
  "max_rounds": 5,
  "stop_keywords": ["与张三的聊天", "张三"]
}
```

### 技能特性

#### phone-observe
- 获取当前屏幕状态（JSON 格式）
- 包含 alerts（弹窗）、elements（元素）、texts_top（文本）
- 不改变手机状态

#### phone-plan
- 根据目标 + 当前状态规划下一步操作
- 仅输出一条指令（<30 汉字）
- 敏感操作检测（发消息/支付/删除等）
- 信息不足时要求再观察

#### phone-control
- 通过 AutoGLM 执行自然语言指令
- 超时控制（默认 30 秒）
- 错误处理与排错建议
- 敏感操作需先确认

#### phone-loop
- 串行执行 observe → plan → act → observe
- 自动判断任务达成
- 最大轮次限制（默认 3）
- 失败保护与排错建议
- 支持敏感操作确认

### 技能协作流程

```
用户目标
  ↓
phone-loop (协调者)
  ↓
phone-observe → phone-plan → phone-control
  ↓
达成？ → 否 → 继续
  ↓ 是
  完成
```

### 示例

#### 示例 1：给张三发消息

```
/phone-loop 目标：在微信中搜索张三并发送消息"你好"；轮次：5
```

**执行流程：**
1. observe: 桌面
2. plan: 打开微信
3. control: ✅ 打开微信
4. observe: 微信首页
5. plan: 点击搜索
6. control: ✅ 点击搜索
7. observe: 搜索页
8. plan: 在搜索框输入 张三 并回车
9. control: ✅ 在搜索框输入 张三 并回车
10. observe: 搜索结果
11. plan: 点击 张三
12. control: ✅ 点击 张三
13. observe: 聊天界面
14. plan: [敏感操作] 需要确认
15. 用户: 确认
16. control: ✅ 在输入框输入 你好 并发送
17. observe: 已发送
18. ✅ 任务达成

#### 示例 2：敏感操作确认

```
/phone-loop 目标：给张三发消息；轮次：5
```

当到达发送消息步骤时，会输出：

```
⚠️ 需要确认：是否发送消息给张三？（回复'确认'后继续执行）
当前轮次: Round 5
待执行指令: 在输入框输入 你好 并发送
```

用户回复"确认"后继续执行。

### 技能文档

每个技能的 `.skill` 文件包含完整的 SKILL.md 文档，详细说明使用方法、参数、示例等。

解压 `.skill` 文件（实为 zip 文件）可查看完整内容：

```bash
unzip -l phone-control.skill
```

---

## 常见问题排查

### 1. llama-server 启动失败
- 检查模型文件路径是否正确
- 不要使用不支持的参数（如 `--log-format`）
- 检查端口 8081 是否被占用

### 2. AutoGLM 报 SOCKS 错误
```bash
./venv/bin/pip install 'httpx[socks]'
```

### 3. ADB 设备 unauthorized
- 在手机上启用"USB 调试"
- 重新连接 ADB
- 检查手机是否弹出授权对话框

### 4. 模型推理缓慢
- 检查 GPU 内存是否足够（M4 推荐 12GB+）
- 尝试减小 `--ctx-size` 参数
- 考虑使用更高精度的量化模型

### 5. 多设备冲突
- 使用 `ANDROID_SERIAL` 环境变量指定目标设备
- 在 `autoglm_service.py` 中设置默认设备

---

## 后台运行建议

使用 systemd 或 launchd 管理后台服务：

### launchd (macOS)

创建 `~/Library/LaunchAgents/com.autoglm.llama-server.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.autoglm.llama-server</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/llama-server</string>
        <string>--model</string>
        <string>/Users/anshi/models/autoglm/AutoGLM-Phone-9B-Q4_K_M.gguf</string>
        <string>--mmproj</string>
        <string>/Users/anshi/models/autoglm/AutoGLM-Phone-9B-mmproj.gguf</string>
        <string>--ctx-size</string>
        <string>16384</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>8081</string>
        <string>--alias</string>
        <string>autoglm-phone-9b</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
```

加载服务：
```bash
launchctl load ~/Library/LaunchAgents/com.autoglm.llama-server.plist
```

---

## 维护

### 重启服务
```bash
# 重启 llama-server
launchctl unload ~/Library/LaunchAgents/com.autoglm.llama-server.plist
launchctl load ~/Library/LaunchAgents/com.autoglm.llama-server.plist

# 重启 AutoGLM Service
# 在 ~/code/Open-AutoGLM 目录重新运行
./venv/bin/python autoglm_service.py
```

### 日志查看
```bash
# llama-server 日志
launchctl logs com.autoglm.llama-server

# AutoGLM Service 日志（运行在终端）
# 直接查看终端输出
```

---

## 性能参考

- **模型加载时间**: ~5 秒
- **首次推理**: ~10-30 秒
- **后续推理**: ~5-15 秒/步
- **GPU 显存占用**: ~8-10GB (M4)
- **完整任务耗时**: 30-120 秒（取决于复杂度）

---

## 参考资源

- [Open-AutoGLM GitHub](https://github.com/zai-org/Open-AutoGLM)
- [llama.cpp](https://github.com/ggerganov/llama.cpp)
- [AutoGLM-Phone-9B](https://huggingface.co/models)

---

*文档版本: 1.0*
*最后更新: 2026-02-01*
