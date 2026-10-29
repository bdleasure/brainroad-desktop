# Notices

This repository contains only BrainRoad's own code and text, released under the MIT License
(see `LICENSE`). It bundles no third-party code and no executables.

It runs inside software that you install separately. BrainRoad does not redistribute it:

| Component | Used for | License | Source |
| --- | --- | --- | --- |
| Hermes Agent and Hermes Desktop (Nous Research) | the app, agent, tools, model settings and plugin host | MIT | https://github.com/NousResearch/hermes-agent |
| Cua Driver (Cua) | Hermes' computer-use tool | MIT | https://github.com/trycua/cua/tree/main/libs/cua-driver |
| `websockets`, `httpx` | phone link connections (from Hermes' own Python environment) | BSD-3-Clause | https://github.com/python-websockets/websockets · https://github.com/encode/httpx |
| FastAPI, Pydantic | the plugin's backend routes (from Hermes' environment) | MIT | https://github.com/fastapi/fastapi · https://github.com/pydantic/pydantic |

Cua publishes some other components (for example Cua Spaces and several streaming components)
under the Functional Source License. BrainRoad does not use them.

Model weights and hosted model services have their own licenses and terms. Choosing a model in
Hermes is separate from this software's license.
