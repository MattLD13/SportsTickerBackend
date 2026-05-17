from ticker_controller.modes.indycar import IndycarMixin
from ticker_controller.fonts import load_monospace_font
import traceback

class Dummy(IndycarMixin):
    def __init__(self):
        self.font = load_monospace_font(10, bold=True)
        # minimal logo functions
        self.get_logo = lambda url, size=None: None
        self._ic_hscroll_x = 0.0
        self._ic_hscroll_ts = 0.0

if __name__ == '__main__':
    try:
        d = Dummy()
        game = {
            'indycar': {
                'drivers': [
                    {'pos': '1', 'abbr': 'ABC', 'car': '23', 'team_logo': '', 'name': 'Driver One', 'car_illustration': ''},
                    {'pos': '2', 'abbr': 'DEF', 'car': '12', 'team_logo': '', 'name': 'Driver Two', 'car_illustration': ''},
                    {'pos': '3', 'abbr': 'GHI', 'car': '7',  'team_logo': '', 'name': 'Driver Three', 'car_illustration': ''}
                ],
                'short_name': 'Some GP',
                'session_type': 'Race'
            },
            'state': 'in'
        }
        img = d.draw_indycar_scroll_card(game)
        img.save('test_indy_scroll.png')
        print('scroll saved test_indy_scroll.png')
        img2 = d.draw_indycar_full(game)
        img2.save('test_indy_full.png')
        print('full saved test_indy_full.png')
    except Exception:
        traceback.print_exc()
        print('exception')
