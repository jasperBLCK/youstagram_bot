import pytest

from app.services.links import Platform, find_link, parse_link


@pytest.mark.parametrize(
    ("url", "platform", "media_id"),
    [
        ("https://www.youtube.com/watch?v=jNQXAC9IVRw&t=10s", Platform.YOUTUBE, "jNQXAC9IVRw"),
        ("https://youtu.be/jNQXAC9IVRw?si=abc", Platform.YOUTUBE, "jNQXAC9IVRw"),
        ("https://youtube.com/shorts/jNQXAC9IVRw", Platform.YOUTUBE, "jNQXAC9IVRw"),
        ("https://m.youtube.com/watch?v=jNQXAC9IVRw", Platform.YOUTUBE, "jNQXAC9IVRw"),
        ("https://www.instagram.com/reel/C1a2B3c4D5e/?igsh=xyz", Platform.INSTAGRAM, "C1a2B3c4D5e"),
        ("https://instagram.com/p/C1a2B3c4D5e/", Platform.INSTAGRAM, "C1a2B3c4D5e"),
        ("https://www.instagram.com/someuser/reel/C1a2B3c4D5e/", Platform.INSTAGRAM, "C1a2B3c4D5e"),
        (
            "https://www.tiktok.com/@scout2015/video/6718335390845095173?lang=en",
            Platform.TIKTOK,
            "6718335390845095173",
        ),
        ("https://vm.tiktok.com/ZMabc123/", Platform.TIKTOK, None),
    ],
)
def test_parse_supported(url: str, platform: Platform, media_id: str | None) -> None:
    link = parse_link(url)
    assert link is not None
    assert link.platform == platform
    assert link.media_id == media_id


def test_youtube_normalized_and_cache_key() -> None:
    a = parse_link("https://youtu.be/jNQXAC9IVRw")
    b = parse_link("https://www.youtube.com/watch?v=jNQXAC9IVRw&list=PL1")
    assert a is not None and b is not None
    assert a.url == b.url == "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    assert a.cache_key("video") == b.cache_key("video") != a.cache_key("audio")


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/watch?v=jNQXAC9IVRw",
        "https://www.youtube.com/channel/UC123",
        "https://www.instagram.com/someuser/",
        "not a url",
    ],
)
def test_parse_unsupported(url: str) -> None:
    assert parse_link(url) is None


def test_find_link_in_text() -> None:
    link = find_link("глянь это https://youtu.be/jNQXAC9IVRw!!")
    assert link is not None and link.media_id == "jNQXAC9IVRw"
    assert find_link("просто текст") is None
    assert find_link(None) is None
