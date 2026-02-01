#!/usr/bin/env python3
"""
AutoGLM HTTP Service
暴露 /run 接口供 OpenClaw 调用
"""
import subprocess
import time
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import uvicorn

app = FastAPI(title="AutoGLM Phone Agent Service")

# 强制只使用局域网设备
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
