"""Keep familiar race names distinct from sponsor titles and circuit names."""

import pytest

from ticker.shared.sports_display import racing_short_name


pytestmark = pytest.mark.critical


@pytest.mark.parametrize("series,event,track,expected", [
    ("nascar", "DAYTONA 500", "Daytona International Speedway", "Daytona 500"),
    ("nascar", "Coca-Cola 600", "Charlotte Motor Speedway", "Coke 600"),
    ("nascar", "Cook Out Southern 500", "Darlington Raceway", "Southern 500"),
    ("nascar", "Brickyard 400 presented by PPG", "Indianapolis Motor Speedway", "Brickyard 400"),
    ("nascar", "Freeway Insurance 500", "Phoenix Raceway", "Phoenix"),
    ("nascar", "Straight Talk Wireless 500", "Phoenix Raceway", "Phoenix"),
    ("nascar", "YellaWood 500", "Talladega Superspeedway", "Talladega"),
    ("nascar", "Goodyear 400", "Darlington Raceway", "Darlington"),
    ("nascar", "Coke Zero Sugar 400", "Daytona International Speedway", "Daytona 400"),
    ("nascar", "Bass Pro Shops Night Race", "Bristol Motor Speedway", "Bristol Night"),
    ("nascar", "DuraMAX Texas Grand Prix Powered by RelaDyne", "Circuit of The Americas", "COTA"),
    ("nascar", "Enjoy Illinois 300", "World Wide Technology Raceway", "Gateway"),
    ("nascar", "Cook Out Clash at Bowman Gray", "Bowman Gray Stadium", "The Clash"),
    ("nascar", "America 250 Florida Duel at DAYTONA", "Daytona International Speedway", "Daytona Duel"),
    ("nascar", "NASCAR All-Star Race", "Dover Motor Speedway", "All-Star Race"),
    ("wec", "FIA WEC - 6 Hours of Barcelona", "Circuito de Barcelona", "Barcelona 6h"),
    ("wec", "TotalEnergies 6 Hours of Spa-Francorchamps", "Circuit de Spa-Francorchamps", "Spa 6h"),
    ("wec", "24 Hours of Le Mans", "Circuit de la Sarthe", "Le Mans 24h"),
    ("wec", "Lone Star Le Mans", "Circuit of The Americas", "Lone Star Le Mans"),
    ("wec", "6 Hours of Fuji", "Fuji Speedway", "Fuji 6h"),
    ("wec", "Bapco Energies 8 Hours of Bahrain", "Bahrain International Circuit", "Bahrain 8h"),
    ("imsa", "29th Annual Motul Petit Le Mans", "ROAD ATLANTA", "Petit Le Mans"),
    ("imsa", "Rolex 24 At Daytona", "Daytona International Speedway", "Rolex 24"),
    ("imsa", "Mobil 1 Twelve Hours of Sebring Presented by Cadillac", "Sebring International Raceway", "Sebring 12h"),
    ("imsa", "Sahlen's Six Hours of The Glen", "Watkins Glen International", "Watkins Glen 6h"),
    ("imsa", "Motul Course de Monterey", "WeatherTech Raceway Laguna Seca", "Laguna Seca"),
    ("imsa", "Chevrolet Grand Prix", "Canadian Tire Motorsport Park", "Mosport"),
    ("imsa", "TireRack.com Battle on the Bricks", "Indianapolis Motor Speedway", "Indy"),
    ("imsa", "IMSA SportsCar Weekend", "Road America", "Road America"),
    ("imsa", "Acura Grand Prix of Long Beach", "Long Beach", "Long Beach"),
    ("wec", "New Event presented by Sponsor", "Unknown Circuit", "New Event"),
])
def test_race_short_names(series, event, track, expected):
    assert racing_short_name(series, event, track) == expected


def test_missing_event_uses_the_known_circuit_without_inventing_a_race_title():
    assert racing_short_name("imsa", "", "Road Atlanta") == "Road Atlanta"


def test_missing_identity_remains_explicit():
    assert racing_short_name("imsa", "", "") == "IMSA"
