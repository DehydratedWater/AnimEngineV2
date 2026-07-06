import os

# force offscreen rendering for all tests before Qt loads
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
