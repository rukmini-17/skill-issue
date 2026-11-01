# How to get a quote

Send `POST /quote` with a JSON body containing `items`. Each item has `sku`, `unitCents` and `qty`. The response has `subtotal`, `shipping` and `total`.
