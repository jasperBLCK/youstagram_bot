from app.services.downloader import select_audio_format, select_youtube_format

MB = 1024 * 1024
FORMATS = [
    {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a", "abr": 128, "filesize": 3 * MB},
    {"format_id": "251", "ext": "webm", "vcodec": "none", "acodec": "opus", "abr": 160, "filesize": 4 * MB},
    {
        "format_id": "136",
        "ext": "mp4",
        "vcodec": "avc1.4d401f",
        "acodec": "none",
        "height": 720,
        "filesize": 60 * MB,
    },
    {
        "format_id": "398",
        "ext": "mp4",
        "vcodec": "av01.0.05M",
        "acodec": "none",
        "height": 720,
        "filesize": 40 * MB,
    },
    {
        "format_id": "135",
        "ext": "mp4",
        "vcodec": "avc1.4d401e",
        "acodec": "none",
        "height": 480,
        "filesize": 30 * MB,
    },
    {
        "format_id": "137",
        "ext": "mp4",
        "vcodec": "avc1.640028",
        "acodec": "none",
        "height": 1080,
        "filesize": 20 * MB,
    },
    {
        "format_id": "18",
        "ext": "mp4",
        "vcodec": "avc1.42001E",
        "acodec": "mp4a",
        "height": 360,
        "filesize": 10 * MB,
    },
]


def test_prefers_best_fitting_h264_under_720p() -> None:
    assert select_youtube_format(FORMATS, 50 * MB, 300) == "135+140"


def test_uses_720p_when_budget_allows() -> None:
    assert select_youtube_format(FORMATS, 2000 * MB, 300) == "136+140"


def test_falls_back_to_progressive() -> None:
    assert select_youtube_format(FORMATS, 12 * MB, 300) == "18"


def test_nothing_fits() -> None:
    assert select_youtube_format(FORMATS, 1 * MB, 300) is None


def test_audio_respects_mp3_estimate() -> None:
    assert select_audio_format(FORMATS, 50 * MB, 300) == "251"
    assert select_audio_format(FORMATS, 50 * MB, 3 * 3600) is None
