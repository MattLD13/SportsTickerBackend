from ticker_controller.stadium import inning_half


def test_inning_half():
    """"BOT 5TH" contains "T ", which is what the old test matched on.

    Every bottom half read as a top half, so the arrow pointed the wrong way
    and the ball-strike count sat on the wrong club.
    """
    cases = [
        ('Top 5th', 'top'),
        ('Bot 5th', 'bot'),
        ('Bottom 5th', 'bot'),
        ('^7TH', 'top'),          # shortened forms used by the compact strip
        ('V7TH', 'bot'),
        # Between halves there is no half to point at.
        ('Mid 5th', 'break'),
        ('End 5th', 'break'),
        ('FINAL', 'break'),
        ('', 'break'),
    ]
    for status, expected in cases:
        assert inning_half(status) == expected, status

    # An explicit flag on the payload wins over the text.
    assert inning_half('Mid 5th', {'isTop': True}) == 'top'
    assert inning_half('Top 5th', {'isTop': False}) == 'bot'
