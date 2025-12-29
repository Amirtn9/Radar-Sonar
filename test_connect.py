import asyncio
import json
import websockets
import sys

# --- مشخصات سرور مقصد را اینجا وارد کن ---
TARGET_IP = "IP_SERVER_MAGHSAD"  # آی‌پی سروری که مانیتور نمیشه
TARGET_PORT = 8080               # پورت ایجنت (پیش‌فرض 8080)
TARGET_PASS = "PASSWORD_SERVER"  # پسورد سرور مقصد

async def test_agent():
    uri = f"ws://{TARGET_IP}:{TARGET_PORT}"
    print(f"🔄 Connecting to {uri} ...")
    
    try:
        async with websockets.connect(
            uri,
            open_timeout=5,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
            max_size=None,
        ) as ws:
            print("✅ Connection Established!")
            
            # 1. Send Token/Password
            print("📤 Sending Auth Token...")
            await ws.send(TARGET_PASS)
            
            # 2. Send multiple commands to verify the connection stays alive
            payload = {"action": "get_stats"}
            for i in range(3):
                print(f"📤 Sending Command: get_stats (#{i+1})")
                await ws.send(json.dumps(payload))
                response = await asyncio.wait_for(ws.recv(), timeout=5)
                print(f"📥 Response: {response}")
                await asyncio.sleep(2)
            
    except ConnectionRefusedError:
        print("❌ Error: Connection Refused. (پورت بسته است یا ایجنت اجرا نشده)")
    except asyncio.TimeoutError:
        print("❌ Error: Timeout. (فایروال پورت را بسته یا آی‌پی اشتباه است)")
    except Exception as e:
        print(f"❌ General Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_agent())