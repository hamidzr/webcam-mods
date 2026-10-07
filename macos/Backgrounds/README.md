# Built-in backgrounds

These JPEGs ship in the macOS app's `Contents/Resources/Backgrounds` directory.
All are 1600x900, with neutral colors and space behind a centered speaker.
They work offline. Existing samples under `assets/sample-backgrounds` are separate.

| File | Gallery name | Origin |
| --- | --- | --- |
| `warm-study.jpg` | Warm study | AI-generated with the built-in imagegen tool, 2026-10-07 |
| `quiet-office.jpg` | Quiet office | AI-generated with the built-in imagegen tool, 2026-10-07 |
| `soft-shelves.jpg` | Soft shelves | Photo by ROCKETMANN TEAM on Pexels |

## Stock photo credit

[Green Plant on Brown Wooden Shelf by ROCKETMANN TEAM](https://www.pexels.com/photo/green-plant-on-brown-wooden-shelf-9507218/).
Downloaded 2026-10-07 from Pexels, center-cropped to 16:9, resized and JPEG-compressed.
[Pexels License](https://www.pexels.com/license/) permits free use and modification,
including use in apps. This asset retains its Pexels license; the repository's
GPL license does not relicense it.

## Generation prompts

Generated using the built-in imagegen tool. Outputs were center-cropped to 16:9,
resized to 1600x900 and JPEG-compressed at quality 86 with ImageMagick. No generated
text or signage is intended to be legible.

### Warm study

```text
Use case: photorealistic-natural
Asset type: built-in 16:9 webcam replacement background, single landscape image, 1920x1080 composition.
Primary request: an ordinary, believable quiet home office BACK WALL behind a seated remote worker. Photograph from laptop webcam height, level straight-on perspective at approximately 1.2 meters height, looking across a modest room about 2 meters deep. Empty room, no person. Broad uninterrupted warm off-white painted wall across center 65% of frame where person's head and torso will overlay. At far left a small simple light oak bookcase with a handful of plain muted books and a small ordinary houseplant; low cabinet along bottom edge, subtle soft daylight from an unseen window to the right. Modest lived-in apartment office, competent professional remote work atmosphere, not a luxury designer interior. Natural slight wall texture, realistic shadows, soft neutral lighting, restrained gray beige sage palette, moderate webcam-like softness rather than tack-sharp real-estate photography. Rear wall fills most of frame, no foreground desk or chair, little visible floor or ceiling. No labels, text, posters, logos, watermarks, screens, people, dramatic light beams or oversaturated colors. Single whole photograph, not a collage.
```

### Quiet office

```text
Use case: photorealistic-natural
Asset type: single landscape 16:9 webcam replacement background photo.
Primary request: a very ordinary private OFFICE BACK WALL as seen behind someone seated at a laptop during a professional work call. Empty room, no person. Camera at seated webcam height 1.2 meters, level horizon, natural perspective, rear wall 2 meters away. Broad uncluttered matte pale gray wall occupies center 70 percent, soft white painted door near far right, low neutral wood storage cabinet at bottom left with two unlabelled folders and a small green plant. Practical modest office, believable everyday space, not luxury or a stock real-estate showroom. Gentle diffuse ambient daylight, no visible sunbeams, no bright visible windows, no dramatic shadows. Cool-neutral gray and warm oak tones, slight photographic softness appropriate to a webcam, restrained contrast, subtle imperfections in wall texture. Frame mostly wall, little floor or ceiling, no foreground workstation or chair. No people, text, logo, watermark, clocks, monitors, framed art or distracting objects. Single photograph, not collage, landscape aspect 16:9.
```

## Maintenance

Keep catalog filenames/titles in `BuiltInBackground.catalog` aligned with these
assets. The app build copies the images and this credits file into the bundle.
`just menu-check` verifies that every catalog image decodes at 1600x900 and that
background selections survive saved configuration encoding.

