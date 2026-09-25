// Единственный NetworkService приложения (состояние сети и результат единственного замера скорости).
import { setConnectivity } from "../core/api/http.js";
import { measure } from "../core/network/bandwidth.js";
import { createNetworkService } from "../core/network/network.js";
import * as store from "../core/state/store.js";

export const network = createNetworkService({ measure, settings: { get: store.setting, set: store.setSetting } });
setConnectivity(network);
