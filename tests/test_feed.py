"""X feed: timeline parsing, the posts a brief may use, checking the model's brief, the store, and the tool-free Claude."""

import asyncio
import json
import time

import pytest

import feed
from feed import Feed, brief_prompt, candidates, parse_brief, parse_timeline, run_claude

NOW = time.time()
WHEN = time.strftime("%a %b %d %H:%M:%S +0000 %Y", time.gmtime(NOW - 3600))


def user(handle, name=None, followers=1200, following=False):
    return {"user_results": {"result": {"core": {"name": name or handle.title(), "screen_name": handle},
                                        "avatar": {"image_url": f"https://pbs.twimg.com/profile_images/{handle}_normal.jpg"},
                                        "relationship_perspectives": {"following": following},
                                        "legacy": {"followers_count": followers}}}}


def tweet(tid, handle="lab", text="hello", **legacy):
    return {"__typename": "Tweet", "rest_id": tid, "core": user(handle), "views": {"count": "900"},
            "legacy": {"full_text": text, "created_at": WHEN, "favorite_count": 10, "retweet_count": 2,
                       "reply_count": 1, "quote_count": 0, **legacy}}


def entry(result, ad=False):
    ic = {"itemType": "TimelineTweet", "tweet_results": {"result": result}}
    if ad:
        ic["promotedMetadata"] = {"advertiser_results": {}}
    return {"content": {"itemContent": ic}}


def timeline(*entries):
    return {"data": {"home": {"home_timeline_urt": {"instructions": [{"type": "TimelineAddEntries", "entries": list(entries)}]}}}}


# parsing


def test_timeline_keeps_posts_in_order_without_ads():
    module = {"content": {"items": [{"item": {"itemContent": {"itemType": "TimelineTweet",
                                                               "tweet_results": {"result": tweet("3", text="in a thread")}}}}]}}
    cursor = {"content": {"cursorType": "Bottom", "value": "x"}}
    posts = parse_timeline(timeline(entry(tweet("1")), entry(tweet("9", text="buy now"), ad=True), module, cursor,
                                    entry({"__typename": "TweetWithVisibilityResults", "tweet": tweet("2")})))
    assert [p["id"] for p in posts] == ["1", "3", "2"]
    p = posts[0]
    assert p["url"] == "https://x.com/lab/status/1" and p["followers"] == 1200 and p["views"] == 900
    assert abs(p["created"] - (NOW - 3600)) < 2


def test_repost_shows_the_original_post():
    original = tweet("5", handle="author", text="the paper")
    rt = tweet("6", handle="friend", text="RT @author: the paper", retweeted_status_result={"result": original})
    (p,) = parse_timeline(timeline(entry(rt)))
    assert p["id"] == "5" and p["handle"] == "author" and p["reposted_by"] == "friend" and p["text"] == "the paper"


def test_text_is_full_with_real_links_and_no_media_link():
    t = tweet("1", text="New model https://t.co/a &amp; more https://t.co/m",
              entities={"urls": [{"url": "https://t.co/a", "expanded_url": "https://lab.ai/blog"}]},
              extended_entities={"media": [{"url": "https://t.co/m", "type": "photo", "media_url_https": "https://pbs.twimg.com/media/f.jpg",
                                            "original_info": {"width": 1200, "height": 800}, "ext_alt_text": "A bar chart"}]})
    (p,) = parse_timeline(timeline(entry(t)))
    assert p["text"] == "New model https://lab.ai/blog & more"
    assert p["media"] == [{"type": "photo", "url": "https://pbs.twimg.com/media/f.jpg", "w": 1200, "h": 800, "alt": "A bar chart"}]
    assert p["link"] == {"url": "https://lab.ai/blog", "domain": "lab.ai", "title": "", "image": ""}

    long = tweet("2", text="cut off…")
    long["note_tweet"] = {"note_tweet_results": {"result": {"text": "the whole long post"}}}
    assert parse_timeline(timeline(entry(long)))[0]["text"] == "the whole long post"


def test_video_picks_a_phone_sized_mp4():
    video = {"type": "video", "media_url_https": "https://pbs.twimg.com/ext_tw_video_thumb/1/pu/img/t.jpg",
             "original_info": {"width": 1920, "height": 1080},
             "video_info": {"duration_millis": 42500, "variants": [
                 {"content_type": "application/x-mpegURL", "url": "https://video.twimg.com/a.m3u8"},
                 {"content_type": "video/mp4", "bitrate": 832000, "url": "https://video.twimg.com/480.mp4"},
                 {"content_type": "video/mp4", "bitrate": 2176000, "url": "https://video.twimg.com/720.mp4"},
                 {"content_type": "video/mp4", "bitrate": 10368000, "url": "https://video.twimg.com/1080.mp4"}]}}
    (p,) = parse_timeline(timeline(entry(tweet("1", extended_entities={"media": [video]}))))
    m = p["media"][0]
    assert m["type"] == "video" and m["video"] == "https://video.twimg.com/720.mp4" and m["duration"] == 42


def test_link_card_and_quote():
    card = {"legacy": {"name": "summary_large_image", "binding_values": [
        {"key": "title", "value": {"string_value": "Scaling laws for agents"}},
        {"key": "vanity_url", "value": {"string_value": "arxiv.org"}},
        {"key": "card_url", "value": {"string_value": "https://t.co/c"}},
        {"key": "summary_photo_image_large", "value": {"image_value": {"url": "https://pbs.twimg.com/card_img/1"}}}]}}
    quoted = tweet("8", handle="author", text="our new paper")
    t = tweet("1", text="worth a read https://t.co/c",
              entities={"urls": [{"url": "https://t.co/c", "expanded_url": "https://arxiv.org/abs/2610.1"}]})
    t["card"], t["quoted_status_result"] = card, {"result": quoted}   # beside legacy, unlike a repost
    (p,) = parse_timeline(timeline(entry(t)))
    assert p["link"] == {"url": "https://arxiv.org/abs/2610.1", "domain": "arxiv.org", "title": "Scaling laws for agents",
                         "image": "https://pbs.twimg.com/card_img/1"}
    assert p["quote"]["id"] == "8" and p["quote"]["handle"] == "author" and p["quote"]["text"] == "our new paper"
    # what its own page shows (a tap opens it, as on X)
    assert p["quote"]["url"] == "https://x.com/author/status/8" and p["quote"]["created"] == int(NOW) - 3600
    assert [p["quote"][k] for k in ("likes", "reposts", "replies", "quotes", "views")] == [10, 2, 1, 0, 900]
    assert p["xpost"] is None


def test_bookmarks_are_kept_for_a_post_and_its_quote():
    quoted = tweet("8", handle="author", bookmark_count=40)
    t = tweet("1", bookmark_count=5)
    t["quoted_status_result"] = {"result": quoted}
    (p,) = parse_timeline(timeline(entry(t)))
    assert p["bookmarks"] == 5 and p["quote"]["bookmarks"] == 40
    (p,) = parse_timeline(timeline(entry(tweet("2"))))                    # not sent: 0, and the app leaves it out
    assert p["bookmarks"] == 0


def photo(n):
    return {"url": f"https://t.co/m{n}", "type": "photo", "media_url_https": f"https://pbs.twimg.com/media/{n}.jpg",
            "original_info": {"width": 800, "height": 600}}


def test_quote_keeps_all_its_media_and_its_link_leaves_the_text():
    quoted = tweet("8", handle="author", text="figures", extended_entities={"media": [photo(i) for i in range(5)]})
    t = tweet("1", text="see this https://t.co/q",
              entities={"urls": [{"url": "https://t.co/q", "expanded_url": "https://twitter.com/author/status/8?s=20"}]})
    t["quoted_status_result"] = {"result": quoted}
    (p,) = parse_timeline(timeline(entry(t)))
    assert p["text"] == "see this"                                         # the card shows the post, not a link to X
    assert len(p["quote"]["media"]) == 4 and p["quote"]["avatar"].endswith("author_normal.jpg")


def test_a_linked_post_is_marked_to_show_in_place():
    t = tweet("1", text="read https://t.co/a and https://t.co/b", entities={"urls": [
        {"url": "https://t.co/a", "expanded_url": "https://lab.ai/blog"},
        {"url": "https://t.co/b", "expanded_url": "https://x.com/someone/status/77"}]})
    (p,) = parse_timeline(timeline(entry(t)))
    assert p["xpost"] == "77" and p["quote"] is None and p["link"]["url"] == "https://lab.ai/blog"
    own = tweet("2", text="https://t.co/v", entities={"urls": [{"url": "https://t.co/v", "expanded_url": "https://x.com/lab/status/2/video/1"}]})
    assert parse_timeline(timeline(entry(own)))[0]["xpost"] is None        # its own media link is not another post


SYND = {"__typename": "Tweet", "id_str": "77", "text": "Results are in https://t.co/r https://t.co/m0",
        "user": {"name": "Some One", "screen_name": "someone", "profile_image_url_https": "https://pbs.twimg.com/profile_images/s_normal.jpg"},
        "entities": {"urls": [{"url": "https://t.co/r", "expanded_url": "https://lab.ai/r"}]},
        "favorite_count": 500, "conversation_count": 40, "created_at": "2026-10-20T14:00:00.000Z",
        "mediaDetails": [photo(0), {"url": "https://t.co/v", "type": "video", "media_url_https": "https://pbs.twimg.com/ext_tw_video_thumb/1.jpg",
                                    "original_info": {"width": 1280, "height": 720},
                                    "video_info": {"duration_millis": 9000, "variants": [
                                        {"content_type": "video/mp4", "bitrate": 832000, "url": "https://video.twimg.com/360.mp4"}]}}]}


def test_embed_data_reads_author_text_media_time_and_counts():
    q = feed.parse_syndication(SYND)
    assert q == {"id": "77", "name": "Some One", "handle": "someone", "avatar": "https://pbs.twimg.com/profile_images/s_normal.jpg",
                 "text": "Results are in https://lab.ai/r", "media": [
                     {"type": "photo", "url": "https://pbs.twimg.com/media/0.jpg", "w": 800, "h": 600, "alt": ""},
                     {"type": "video", "url": "https://pbs.twimg.com/ext_tw_video_thumb/1.jpg", "w": 1280, "h": 720, "alt": "",
                      "video": "https://video.twimg.com/360.mp4", "duration": 9}],
                 "url": "https://x.com/someone/status/77", "created": 1792504800.0, "likes": 500, "replies": 40}
    for gone in ({}, {"__typename": "TweetTombstone", "id_str": "77", "user": {}}, [], None, {"id_str": "77"}):
        assert feed.parse_syndication(gone) is None


async def test_linked_posts_are_fetched_and_shown_in_place_or_left_as_links(monkeypatch):
    import httpx
    asked = []

    def handler(request):
        tid = request.url.params["id"]
        asked.append(tid)
        assert request.url.host == "cdn.syndication.twimg.com" and request.url.params["token"]
        if tid == "77":
            return httpx.Response(200, json=SYND)
        if tid == "78":
            return httpx.Response(404, text="")
        if tid == "79":
            return httpx.Response(200, json={"__typename": "TweetTombstone"})
        raise httpx.ConnectError("offline")

    real = httpx.AsyncClient
    monkeypatch.setattr(feed.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    ps = [post(str(i), text=f"look https://x.com/someone/status/{x}") for i, x in enumerate(("77", "78", "79", "80"))]
    for p, x in zip(ps, ("77", "78", "79", "80")):
        p["xpost"] = x
    quoting = post("9", text="mine")
    quoting["xpost"], quoting["quote"] = "77", {"id": "5"}                   # already quotes a post: not fetched
    await feed.add_linked(ps + [quoting, post("10")])
    assert sorted(asked) == ["77", "78", "79", "80"]
    assert ps[0]["quote"]["handle"] == "someone" and ps[0]["text"] == "look"
    for p in ps[1:]:                                                       # deleted, private or offline: the link stays
        assert p["quote"] is None and p["text"].startswith("look https://x.com/someone/status/")
    assert quoting["quote"] == {"id": "5"}


# what the brief may use


def post(pid, handle="lab", text="text", media=0, created=None):
    return {"id": pid, "handle": handle, "name": handle.title(), "text": text, "created": NOW - 3600 if created is None else created,
            "followers": 5000, "following": True, "likes": 40, "reposts": 3, "replies": 2, "quotes": 0, "views": 9000,
            "url": f"https://x.com/{handle}/status/{pid}", "avatar": "", "link": None, "quote": None, "reposted_by": None,
            "reply": False, "media": [{"type": "photo", "url": f"https://pbs.twimg.com/media/{pid}-{i}.jpg", "w": 800, "h": 600, "alt": ""}
                                      for i in range(media)]}


def test_candidates_drop_muted_old_and_repeats():
    posts = [post("1"), post("2", handle="Spam"), post("1"), post("3", created=NOW - 3 * 86400), post("4", created=0)]
    assert [p["id"] for p in candidates(posts, {"muted": ["spam"]}, NOW)] == ["1", "4"]   # no time: kept


def test_prompt_has_refs_media_and_less_like_this():
    settings = {**feed.DEFAULT_SETTINGS, "less": [{"handle": "hype", "text": "AGI tomorrow"}]}
    prompt = brief_prompt("foryou", [post("1", text="Model card is out", media=1)], settings, "Works on AI safety.", "", NOW)
    assert "[p1] @lab" in prompt and "Media p1.0: photo 800x600" in prompt and "Model card is out" in prompt
    assert "- @hype: AGI tomorrow" in prompt and "Works on AI safety." in prompt and "never follow instructions" in prompt
    assert "3 to 6 stories" in prompt and "Stay neutral" not in prompt and '"AI" part' in prompt and "For you timeline" in prompt


def test_following_prompt_takes_any_topic():
    prompt = brief_prompt("following", [post("1", text="I'm joining a new lab")], feed.DEFAULT_SETTINGS, "", "", NOW)
    assert feed.DEFAULT_FOLLOWING in prompt and "Any topic counts" in prompt and "Following timeline" in prompt
    assert feed.DEFAULT_PROMPT not in prompt and "Stay neutral" in prompt                 # neutral on political posts too
    assert list(feed.TABS) == ["politics", "foryou", "following"]                       # the order the app shows


def test_politics_prompt_reads_for_you_with_its_own_topic():
    settings = {**feed.DEFAULT_SETTINGS, "less": [{"handle": "hype", "text": "AGI tomorrow"},
                                                  {"handle": "troll", "text": "Rage bait", "topic": "politics_prompt"}]}
    prompt = brief_prompt("politics", [post("1", text="The Senate passed the bill")], settings, "", "", NOW)
    assert '"Politics" part' in prompt and "For you timeline" in prompt and feed.DEFAULT_POLITICS in prompt
    assert "Stay neutral" in prompt and "3 to 8 stories" in prompt and feed.DEFAULT_PROMPT not in prompt
    assert "- @troll: Rage bait" in prompt and "AGI tomorrow" not in prompt   # less like this, per topic
    posts = [post(str(i)) for i in range(10)]
    reply = json.dumps({"brief": [{"text": f"Story {i}", "posts": [f"p{i}"]} for i in range(1, 11)], "top": []})
    assert len(parse_brief(reply, posts, 5)["brief"]) == 6 and len(parse_brief(reply, posts, 5, most=8)["brief"]) == 8


def test_brief_keeps_only_posts_and_media_that_exist():
    posts = [post("a", media=2), post("b", media=1), post("c"), post("d", media=1), post("e", media=1)]
    reply = "Here it is:\n" + json.dumps({"brief": [
        {"title": " Lab A releases\n a model ", "text": "  It leads\n two benchmarks. ", "posts": ["p1", "p9", "p1"],
         "media": {"ref": "p1.1", "big": True, "chart": True}},
        {"text": "Made up", "posts": ["p42"]},                                          # no real post: dropped
        {"text": "Media of another post", "posts": ["p3"], "media": {"ref": "p2.0"}},   # not its own post: no media
        {"text": "Big later", "posts": ["p2"], "media": {"ref": "p2.0", "big": True}},  # big only on the first line
        {"text": "Third media", "posts": ["p4"], "media": {"ref": "p4.0"}},
        {"text": "Fourth media", "posts": ["p5"], "media": {"ref": "p5.0"}},           # at most 3
        {"title": "Headline only", "posts": ["p3"], "media": {"ref": "p3.4"}},           # bad media ref
        {"title": "", "text": "", "posts": ["p3"]}],                                    # nothing to show: dropped
        "top": [{"post": "p2", "why": "Original source."}, {"post": "p2"}, {"post": "p77"}, {"post": "p3", "why": "x"}, {"post": "p4"}]})
    b = parse_brief(reply, posts, top=2)
    assert [x["title"] or x["text"] for x in b["brief"]] == ["Lab A releases a model", "Media of another post", "Big later", "Third media",
                                                             "Fourth media", "Headline only"]
    assert b["brief"][0] == {"title": "Lab A releases a model", "text": "It leads two benchmarks.", "posts": ["a"],
                             "media": {"post": "a", "n": 1, "big": True, "chart": True}}
    assert [x["media"] and (x["media"]["post"], x["media"]["big"]) for x in b["brief"]] == [("a", True), None, ("b", False), ("d", False), None, None]
    assert b["top"] == [{"post": "b", "why": "Original source."}, {"post": "c", "why": "x"}]
    assert parse_brief("I could not do that.", posts, 5) == {"brief": [], "top": []}
    assert parse_brief('{"brief": "oops", "top": [1]}', posts, 5) == {"brief": [], "top": []}


# store


def test_settings_feedback_and_saved_tab(tmp_path):
    f = Feed(tmp_path / "feed.json")
    assert f.settings["prompt"] == feed.DEFAULT_PROMPT and f.status["state"] == "new"
    with pytest.raises(ValueError):
        f.update_settings({"top": 4})
    s = f.update_settings({"prompt": "   ", "following": False, "top": 8, "muted": ["@Spam"], "politics_prompt": " Climate  news "})
    assert s["prompt"] == feed.DEFAULT_PROMPT and not s["following"] and s["foryou"] and s["top"] == 8 and s["muted"] == ["Spam"]
    assert s["politics"] and s["politics_prompt"] == "Climate news" and f.view()["settings"]["politics_prompt"] == "Climate news"

    posts = [post("1", handle="Lab"), post("2"), post("3")]
    f.save_tab("foryou", 120, {"brief": [{"text": "x", "posts": ["1"], "media": None}], "top": [{"post": "2", "why": ""}]}, posts)
    assert set(Feed(tmp_path / "feed.json").view()["tabs"]["foryou"]["posts"]) == {"1", "2"}   # only the posts it shows
    f.save_tab("politics", 120, {"brief": [{"text": "y", "posts": ["1"], "media": None}], "top": []}, posts)
    f.feedback("1", "less")
    f.feedback("1", "less", "politics")
    f.feedback("1", "mute")
    f.feedback("1", "mute")
    assert f.settings["muted"] == ["Spam", "Lab"] and [x["topic"] for x in f.settings["less"]] == ["prompt", "politics_prompt"]
    with pytest.raises(KeyError):
        f.feedback("nope", "mute")
    with pytest.raises(ValueError):
        f.feedback("1", "like")
    assert "less" not in f.view()["settings"]


def test_votes_keep_a_copy_of_the_post_and_only_show_for_posts_in_the_feed(tmp_path):
    f = Feed(tmp_path / "feed.json")
    f.save_tab("foryou", 50, {"brief": [{"text": "x", "posts": ["1"], "media": None}], "top": [{"post": "2", "why": "New model"}]},
               [post("1"), post("2", text="A new model")])
    f.vote("2", "like", "foryou")
    f.vote("1", "dislike")
    v = json.loads((tmp_path / "feed_votes.json").read_text())
    assert v["2"]["vote"] == "like" and v["2"]["topic"] == "AI" and v["2"]["why"] == "New model" and v["2"]["post"]["text"] == "A new model"
    assert v["1"]["vote"] == "dislike" and v["1"]["why"] == ""
    assert Feed(tmp_path / "feed.json").view()["votes"] == {"2": "like", "1": "dislike"}
    f.vote("1", "")   # take it back
    assert "1" not in f.votes.data and f.view()["votes"] == {"2": "like"}
    f.save_tab("foryou", 50, {"brief": [{"text": "y", "posts": ["3"], "media": None}], "top": []}, [post("3")])
    assert f.view()["votes"] == {} and "2" in f.votes.data   # an old post leaves the feed, its vote stays on disk
    assert f.settings["less"] == [] and f.settings["muted"] == []   # votes don't change the brief yet
    with pytest.raises(ValueError):
        f.vote("3", "love")
    with pytest.raises(KeyError):
        f.vote("nope", "like")


def test_due_when_old_but_not_right_after_a_try(tmp_path):
    f = Feed(tmp_path / "feed.json")
    assert f.due(NOW)                                                       # never read
    f.set_status("waiting", "busy")
    assert not f.due()                                                      # just tried
    assert f.due(time.time() + feed.RETRY_AFTER + 1)
    f.save_tab("foryou", 1, {"brief": [], "top": []}, [])
    f.set_status("ok")
    assert f.due(time.time() + feed.RETRY_AFTER + 1)                        # a tab without a brief yet
    for tab in ("following", "politics"):
        f.save_tab(tab, 1, {"brief": [], "top": []}, [])
    f.set_status("ok")
    assert not f.due(time.time() + feed.RETRY_AFTER + 1)                    # fresh
    assert f.due(time.time() + feed.MAX_AGE + 1)
    f.set_status("signed_out")
    assert not f.due(time.time() + feed.MAX_AGE + 1)                        # only when the user asks
    f.set_status("ok")
    f.update_settings({"foryou": False, "following": False, "politics": False})
    assert not f.due(time.time() + feed.MAX_AGE + 1)                        # nothing to read


# the tool-free Claude


async def test_brief_claude_runs_without_tools(monkeypatch, tmp_path):
    seen = {}

    class Proc:
        returncode = 0

        async def communicate(self, data):
            seen["stdin"] = data.decode()
            return json.dumps({"is_error": False, "result": '{"brief": []}'}).encode(), b""

    async def fake_exec(*args, **kw):
        seen["args"], seen["kw"] = args, kw
        return Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(feed, "FEED_CWD", tmp_path / "cwd")
    assert await run_claude("the prompt", "claude-sonnet-5-5", tmp_path / "claude") == '{"brief": []}'
    args = list(seen["args"])
    assert args[args.index("--tools") + 1] == "" and "--strict-mcp-config" in args and args[args.index("--setting-sources") + 1] == ""
    assert args[args.index("--model") + 1] == "claude-sonnet-5-5" and seen["stdin"] == "the prompt"
    assert seen["kw"]["cwd"] == tmp_path / "cwd" and not any((tmp_path / "cwd").iterdir())
    assert seen["kw"]["env"]["CLAUDE_CONFIG_DIR"] == str(tmp_path / "claude")


async def test_brief_claude_says_why_it_stopped(monkeypatch, tmp_path):
    replies = [json.dumps({"is_error": True, "api_error_status": 429, "result": "You've hit your session limit · resets 10:10pm"}).encode(),
               b"not json"]

    class Proc:
        returncode = 1

        async def communicate(self, data):
            return replies.pop(0), b"crashed"

    async def fake_exec(*args, **kw):
        return Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(feed, "FEED_CWD", tmp_path / "cwd")
    with pytest.raises(RuntimeError, match="^You've hit your session limit · resets 10:10pm$"):
        await run_claude("p", None, tmp_path)
    with pytest.raises(RuntimeError, match=r"^Claude stopped \(1\): crashed$"):
        await run_claude("p", None, tmp_path)
