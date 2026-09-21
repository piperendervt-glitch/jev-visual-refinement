"""Place the single shared player in the map dock, never clone a media owner."""
def dock_player(page, component):
    before, marker, rest = component.partition('<!-- PLAYER_START -->')
    if not marker:
        raise ValueError('player_template_start_missing')
    player, marker, after = rest.partition('<!-- PLAYER_END -->')
    if not marker:
        raise ValueError('player_template_end_missing')
    return page.replace('<!-- SAVED_VIDEO -->', before + after).replace('<!-- SAVED_VIDEO_DOCK -->', player)
