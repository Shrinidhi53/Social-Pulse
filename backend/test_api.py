
import asyncio
import os

import httpx
import websockets
from dotenv import load_dotenv

load_dotenv()

YOUTUBE_KEY = os.getenv("YOUTUBE_API_KEY")
GNEWS_KEY = os.getenv("GNEWS_API_KEY")

JETSTREAM_URL = (
    "wss://jetstream.us-east.bsky.network/xrpc/"
    "network.bsky.jetstream.subscribeEvents"
    "?collections=app.bsky.feed.post&kinds=commit"
)


def test_youtube():
    print("\n--- Testing YouTube ---")

    if not YOUTUBE_KEY:
        print("FAIL: YOUTUBE_API_KEY missing from .env")
        return

    try:
        response = httpx.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet",
                "q": "Tata STRIVE",
                "type": "video",
                "maxResults": 5,
                "key": YOUTUBE_KEY,
            },
            timeout=20,
        )

        data = response.json()

        if response.is_success:
            videos = data.get("items", [])
            print(f"PASS: Received {len(videos)} videos")

            for video in videos:
                snippet = video["snippet"]
                video_id = video["id"]["videoId"]
                print("-", snippet["title"])
                print(
                    "  URL:",
                    f"https://www.youtube.com/watch?v={video_id}",
                )
        else:
            print("FAIL:", data.get("error", {}).get("message", response.status_code))

    except Exception as exc:
        print("FAIL:", type(exc).__name__, str(exc))


def test_gnews():
    print("\n--- Testing GNews ---")

    if not GNEWS_KEY:
        print("FAIL: GNEWS_API_KEY missing from .env")
        return

    try:
        response = httpx.get(
            "https://gnews.io/api/v4/search",
            params={
                "q": '"Tata STRIVE" OR "skill development"',
                "lang": "en",
                "max": 5,
                "apikey": GNEWS_KEY,
            },
            timeout=20,
        )

        data = response.json()

        if response.is_success:
            articles = data.get("articles", [])
            print(f"PASS: Received {len(articles)} articles")

            for article in articles:
                print("-", article.get("title"))
                print("  URL:", article.get("url"))
                print("  Published:", article.get("publishedAt"))
        else:
            print("FAIL:", data.get("errors", data.get("message", response.status_code)))

    except Exception as exc:
        print("FAIL:", type(exc).__name__, str(exc))


async def test_bluesky():
    print("\n--- Testing Bluesky Jetstream ---")
    print("Waiting up to 20 seconds for a public post...")

    try:
        async with websockets.connect(
            JETSTREAM_URL,
            open_timeout=10,
            close_timeout=3,
        ) as ws:
            print("PASS: WebSocket connected")

            while True:
                try:
                    frame = await asyncio.wait_for(
                        ws.recv(), timeout=20
                    )
                except asyncio.TimeoutError:
                    print("No post received within 20 seconds.")
                    break

                event = __import__("json").loads(frame)["payload"]

                if event.get("operation") == "delete":
                    continue

                record = event.get("record", {})
                text = record.get("text")

                if text:
                    print("PASS: Received a live post")
                    print("Text:", text[:300])
                    print("Author DID:", event.get("did"))
                    break

    except Exception as exc:
        print("FAIL:", type(exc).__name__, str(exc))


if __name__ == "__main__":
    test_youtube()
    test_gnews()
    asyncio.run(test_bluesky())
