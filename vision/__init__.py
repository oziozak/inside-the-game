"""Vision AI: video frames in, detected events (source: cv) out.

Runtime code here reads only the rendered video and the team sheet
(match_info.json). `vision.grader` is the one exception: an offline tool that
reads true events to score detections, never imported by the runtime path.
"""
