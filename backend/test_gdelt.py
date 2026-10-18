
import httpx

URL = "https://api.gdeltproject.org/api/v2/doc/doc"

params = {
    "query": '("Tata STRIVE" OR "skill development" OR employability)',
    "mode": "artlist",
    "format": "json",
    "timespan": "7d",
    "maxrecords": 10,
    "sort": "datedesc",
}

try:
    response = httpx.get(
        URL,
        params=params,
        headers={"User-Agent": "SocialPulse/0.1"},
        timeout=30,
    )

    print("HTTP status:", response.status_code)
    print("Content-Type:", response.headers.get("content-type"))
    print("Final URL:", response.url)

    response.raise_for_status()

    # Inspect the response before attempting JSON parsing.
    body = response.text.strip()

    if not body:
        print("ERROR: GDELT returned an empty response.")
    else:
        try:
            data = response.json()
        except ValueError:
            print("ERROR: Response is not JSON.")
            print("Response preview:")
            print(body[:1500])
        else:
            articles = data.get("articles", [])
            print(f"\nArticles returned: {len(articles)}")

            for article in articles:
                print("\nTitle:", article.get("title"))
                print("URL:", article.get("url"))
                print("Domain:", article.get("domain"))
                print("Seen date:", article.get("seendate"))

except httpx.HTTPStatusError as exc:
    print("HTTP error:", exc)
    print("Response preview:", exc.response.text[:1500])

except httpx.RequestError as exc:
    print("Network error:", type(exc).__name__, str(exc))
