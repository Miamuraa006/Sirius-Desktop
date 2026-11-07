# UI artwork provenance

`crystal.png` and `ribbons.png` contain only the crystal M / blue ribbon artwork
extracted from the user's approved `Неоновый интерфейс ассистента SIRIUS.png`
(1536 × 1024). No controls, labels, timestamps, sample history or window borders
are baked into those images. `ui/tools/extract_reference.py` reproduces the
masks. Pillow is required only to regenerate the images, never at app runtime.

The panel geometry remains the JSON's 420 × 660 / 840 × 660 logical units.
Native QML provides every control, history row, state animation, and border.
`send.svg` is a small original local vector; nothing is fetched over the network.
