
import httpx

URL = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"
queries = [
    '"Tata STRIVE"',
    '"Tata STRIVE" OR employability',
    '"skill development" India',
    '"vocational training" India',
    '"youth employment" India',
]

with httpx.Client(timeout=25) as client:
    for query in queries:
        print(f"\n{'=' * 65}")
        print("QUERY:", query)

        try:
            response = client.get(
                URL,
                params={
                    "q": query,
                    "sort": "latest",
                    "limit": 10,
                    "lang": "en",
                },
            )

            print("HTTP:", response.status_code)
            response.raise_for_status()
            posts = response.json().get("posts", [])
            print("RESULTS:", len(posts))

            for item in posts:
                post = item.get("post", {})
                record = post.get("record", {})
                author = post.get("author", {})
                text = record.get("text", "")

                print("\nText:", text[:400])
                print("Author:", author.get("handle"))
                print("Likes:", post.get("likeCount", 0))
                print("Replies:", post.get("replyCount", 0))
                print("URI:", post.get("uri"))

        except Exception as exc:
            print("Search failed:", type(exc).__name__, str(exc))
