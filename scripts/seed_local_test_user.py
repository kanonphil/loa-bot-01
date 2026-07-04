"""로컬에서 실제 Discord OAuth 로그인을 테스트하기 위한 준비 스크립트.
운영 중인 오라클 봇 DB(loa_bot.db)는 전혀 건드리지 않고,
local_test.db라는 별도 파일에 본인 discord_id만 등록한다.

사용법:
    LOA_DB_PATH=local_test.db python scripts/seed_local_test_user.py <본인_디스코드_ID>
"""
import asyncio
import os
import sys

# 어느 위치에서 실행하든 저장소 루트를 import 경로에 넣어준다.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main(discord_id: str) -> None:
    os.environ.setdefault("DISCORD_TOKEN", "unused-for-local-api-only-test")
    os.environ.setdefault("LOA_DB_PATH", "local_test.db")

    import bot.database.manager as db  # DISCORD_TOKEN 세팅 후에 import (config.py가 즉시 읽음)

    await db.init_db()
    await db.set_user_api_key(discord_id, "dummy-loa-key-for-local-test")
    print(f"완료: {discord_id} 를 {db.DB_PATH} 에 등록했습니다.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("사용법: python scripts/seed_local_test_user.py <본인_디스코드_ID>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
