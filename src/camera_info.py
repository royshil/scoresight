class CameraInfo:
    class CameraType:
        OPENCV = "OPENCV"
        NDI = "NDI"
        IP = "IP"
        VIRTUAL = "Virtual"
        FILE = "File"
        URL = "URL"
        SCREEN_CAPTURE = "Screen Capture"
        PHONE = "Phone"

    def __init__(self, description: str, uuid: str, id: str | int, type: str):
        self.description = description
        self.uuid = uuid
        self.id = id
        self.type = type

    def __str__(self):
        return f"{self.description} ({self.id})"
