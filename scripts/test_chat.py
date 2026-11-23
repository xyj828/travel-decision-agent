"""本地联调：直接打 /chat SSE，验证两轮对话（含追问记忆）。"""
import json
import sys
import uuid

import httpx

BASE = "http://127.0.0.1:8088/chat"
CID = str(uuid.uuid4())
UID = "local-test-" + CID[:8]

TURNS = [
    "我在红莲南路地铁站附近，我想要去一个既有倍轻松又有西厅村屋的离得近的商场，帮我推荐。",
    "如果不要求两个品牌同时存在，还有没有距离更近的选择？",
]


def ask(message: str) -> str:
    text = ""
    tools = []
    with httpx.Client(timeout=180.0) as client:
        with client.stream(
            "POST",
            BASE,
            json={"message": message, "userId": UID},
            headers={"Content-Type": "application/json", "makers-conversation-id": CID},
        ) as resp:
            resp.raise_for_status()
            event = None
            for line in resp.iter_lines():
                if line.startswith("event: "):
                    event = line[7:].strip()
                elif line.startswith("data: ") and event:
                    payload = json.loads(line[6:])
                    if event == "text_delta":
                        text += payload.get("delta", "")
                    elif event == "tool_called":
                        tools.append(payload.get("tool"))
                    elif event == "error":
                        print("  [ERROR]", payload, file=sys.stderr)
                    event = None
    print(f"\n调用工具: {tools}")
    print(f"回答:\n{text}\n" + "-" * 70)
    return text


if __name__ == "__main__":
    print(f"conversation_id = {CID}")
    for i, q in enumerate(TURNS, 1):
        print(f"\n===== 第 {i} 轮 用户: {q} =====")
        ask(q)
