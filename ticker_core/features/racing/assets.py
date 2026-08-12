"""Expose shared asset contracts to the racing renderer."""

from ticker_core.assets import AssetView, MemoryAssetView, prepare_car, remove_border_background


RacingAssetService = AssetView
MemoryRacingAssets = MemoryAssetView
process_car_image = prepare_car

__all__ = [
    "MemoryRacingAssets",
    "RacingAssetService",
    "process_car_image",
    "remove_border_background",
]
