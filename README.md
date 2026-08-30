# SimonsVoss MobileKey for Home Assistant

This integration connects **Home Assistant** with the **MobileKey cloud service** by **SimonsVoss**, a system designed to manage the manufacturer's smart locks.

**Architecture overview:**
A **SmartBridge** device, installed on the local network, acts as a gateway and communicates with the locks over **868 MHz radio frequency**. It then reports the lock states upstream to the **MobileKey cloud**. Note that the SmartBridge does **not** expose any direct local API — all communications go through the **SimonsVoss MobileKey cloud APIs**.

Each lock is bound to **one and only one SmartBridge**, which can therefore be considered as a **hub/gateway** for its associated locks.

The integration supports **multiple SmartBridges**, each managing its own set of locks independently.

---

**Key features:**
- 🔒 Monitor and control SimonsVoss smart locks from Home Assistant
- ☁️ Cloud-based communication via the MobileKey API
- 📡 868 MHz lock communication through the SmartBridge gateway
- 🔁 Multi-SmartBridge support
- 🏠 Seamless Home Assistant integration
