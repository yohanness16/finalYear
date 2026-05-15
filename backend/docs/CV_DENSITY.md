# ESP32-CAM Density Pipeline

This project uses a hybrid OpenCV pipeline for bus density estimation from ESP32-CAM frames.

## What the live pipeline does

1. The ESP32-CAM uploads a JPEG frame to `POST /api/v1/gateway/esp32/telemetry`.
2. The backend identifies the bus by `device_id`.
3. The image is analyzed locally with OpenCV.
4. The analyzer returns two views of the frame:
   - an estimated people count
   - a coarse occupancy level: `0 = empty/low`, `1 = normal`, `2 = crowded`
5. The backend stores the result in raw telemetry, updates Redis live state, and broadcasts the live bus position.

## How density is computed

The current implementation uses two signals:

- HOG people detection, which can detect upright pedestrians when the image is suitable.
- A bird-view foreground heuristic, which looks at dark/foreground blobs and overall foreground ratio when the HOG detector misses top-down passengers.

The final density result is derived from the stronger of:

- person count mapped against bus capacity when capacity is known
- foreground coverage mapped to empty/normal/crowded bands

## Why the heuristic exists

A bird-view bus interior frame is not the same as a street-level pedestrian photo. HOG alone can undercount when passengers are seen from above, partially occluded, or compressed into a few visible blobs. The foreground heuristic acts as a fallback so the system still produces a usable density label when HOG misses.

## Current response shape

The gateway returns and stores a `cv` object with:

- `human_count`
- `people_count`
- `crowd_density`
- `is_crowded`
- `method`
- `confidence`
- `foreground_ratio`

## Operational limitations

This is still a heuristic system, not a trained crowd-counting model.

- Exact head count can be wrong when passengers overlap heavily.
- Interior lighting, seat color, window glare, and motion blur can affect the foreground mask.
- The `device_id` is the transport identity, so the backend trusts the firmware to send the correct bus id.

## Good use cases

This approach is best when:

- cameras capture frames at stops or slow-moving intervals
- the main goal is empty vs normal vs crowded classification
- approximate passenger count is acceptable

## If higher accuracy is needed

The next step would be a trained bird-view counting model or a dataset-specific detector for bus interiors, then replacing the foreground heuristic with learned inference while keeping the same gateway contract.