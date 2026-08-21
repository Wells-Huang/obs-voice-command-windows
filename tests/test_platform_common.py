import pytest

from obs_voice_command.platform.common import (
    DisplayInfo,
    PointerBackend,
    locate_point,
    point_to_display_pixels,
)


def test_point_conversion_handles_negative_origin_and_scaling():
    display = DisplayInfo(
        origin_x=-1512.0,
        origin_y=-100.0,
        width_pts=1512.0,
        height_pts=982.0,
        width_px=3024,
        height_px=1964,
        id="retina-left",
        primary=True,
    )

    assert display.contains((-1512.0, -100.0))
    assert point_to_display_pixels((-756.0, 391.0), display) == (1512.0, 982.0)
    assert locate_point((0.0, 0.0), [display]) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("width_pts", 0.0),
        ("height_pts", -1.0),
        ("width_px", 0),
        ("height_px", -1),
    ],
)
def test_display_dimensions_must_be_positive(field, value):
    kwargs = {
        "origin_x": 0.0,
        "origin_y": 0.0,
        "width_pts": 100.0,
        "height_pts": 100.0,
        "width_px": 100,
        "height_px": 100,
    }
    kwargs[field] = value

    with pytest.raises(ValueError, match="must be positive"):
        DisplayInfo(**kwargs)


def test_pointer_backend_protocol_is_platform_neutral():
    class FakeBackend:
        def initialize_coordinate_space(self):
            pass

        def list_displays(self):
            return []

        def get_cursor_position(self):
            return 1.0, 2.0

    assert isinstance(FakeBackend(), PointerBackend)
