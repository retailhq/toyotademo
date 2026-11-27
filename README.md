# Toyota in-store kiosk (portrait touch screen)

Lightweight vehicle finder for Toyota Somerset West, powered by RetailHQ: every range on
toyota.co.za/vehicles with models, colours, prices, monthly estimates, features, gallery, specs and compare.

- `index.html` – the kiosk (open this on the screen)
- `preview.html` – testing aid: shows the kiosk as a 1080x1920 portrait screen on a landscape monitor
- `?store=Name&tag=Text&idle=90` – optional URL settings

Update prices and models: in `_src`, delete `cache/`, run `python fetch_toyota.py`, then `python build_toyota.py`,
then commit and push.
