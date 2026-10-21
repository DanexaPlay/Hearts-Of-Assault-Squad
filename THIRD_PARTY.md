# Third-party components

- **hoi4_lua**, ari-20: https://github.com/ari-20/hoi4_lua,
  pinned release https://github.com/ari-20/hoi4_lua/releases/tag/v0.5.
  Upstream licence: https://github.com/ari-20/hoi4_lua/blob/main/LICENSE (MIT).
  Runtime binaries are downloaded separately, verified against the committed
  manifest and excluded from version control. Retain the upstream licence
  when redistributing its binaries; this repository does not redistribute them.
- **Pillow**: https://github.com/python-pillow/Pillow, HPND licence and
  accompanying third-party notices. Installed separately through pip.
- **Hearts of Iron IV / Men of War: Assault Squad 2**: installed games are
  required and are not included. Maps, models and other game resources are
  read locally. Small interface reference images in `assets/mow-ui` are used
  solely for compatibility/recognition and remain the property of their owners.

Version addresses/layouts in the native adapter are specific to the supported
HOI4 build and were researched using upstream hoi4_lua documentation and local
validation. The independent projects and game publishers do not endorse this bridge.
