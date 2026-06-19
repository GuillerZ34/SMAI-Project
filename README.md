# 🌿 SMAI — Smart Irrigation System

SMAI is an end-to-end smart irrigation system built around an **ESP32**, **Firebase Realtime Database**, an **AI-powered decision agent**, and a **live monitoring dashboard**.

The ESP32 reads soil moisture, air temperature, and air humidity, then uploads the data to Firebase. A Python agent periodically reads that data, asks an LLM (via OpenRouter) whether irrigation is needed, writes the recommendation back to Firebase, and sends a push notification. The ESP32 then picks up that recommendation and activates a relay to water the plants. A Streamlit dashboard displays everything in real time.

## How it works

```
┌──────────┐      sensor data      ┌──────────────┐
│  ESP32   │  ───────────────────► │              │
│ (sensors │                       │   Firebase   │
│ + relay) │  ◄─────────────────── │   Realtime   │
└──────────┘   irrigation command  │   Database   │
                                    │              │
                                    └──────┬───────┘
                                           │
                              reads data / writes recommendation
                                           │
                                    ┌──────▼───────┐        ┌────────────┐
                                    │ Python Agent │ ─────► │ OpenRouter │
                                    │ (decision    │ ◄───── │   (LLM)    │
                                    │  logic)      │        └────────────┘
                                    └──────┬───────┘
                                           │
                                           ▼
                                    push notification
                                       (ntfy.sh)

                                    ┌──────────────┐
                                    │  Streamlit   │  ◄── reads data
                                    │  Dashboard   │      from Firebase
                                    └──────────────┘
```

## Project structure

```
smai-irrigation-system/
├── firmware/
│   └── smai_esp32.ino       # ESP32 firmware (sensors + relay control)
├── agent/
│   └── smai_agente.py       # Python agent: reads sensors, asks the LLM, writes back
├── dashboard/
│   └── smai_dashboard.py    # Streamlit live dashboard
├── firebase/
│   └── reglas_firebase.json # Firebase Realtime Database security rules
├── Auth.env.example         # Template for the agent's environment variables
├── requirements.txt         # Python dependencies
└── LICENSE
```

## Hardware

| Component         | Purpose                          | ESP32 Pin |
|--------------------|----------------------------------|-----------|
| DHT11              | Air temperature & humidity       | GPIO 4    |
| FC-28 soil sensor  | Soil moisture (analog)           | GPIO 34   |
| Relay module       | Controls the water pump/valve    | GPIO 26   |

## Setup

### 1. Firebase

1. Create a Firebase project with a **Realtime Database**.
2. Enable **Email/Password** sign-in under Firebase Authentication.
3. Create the user accounts referenced in the code (ESP32 account and agent account).
4. Apply the rules from `firebase/reglas_firebase.json` to your Realtime Database, matching the UIDs to your own user accounts.

### 2. ESP32 firmware

1. Open `firmware/smai_esp32.ino` in the Arduino IDE.
2. Install the required libraries via **Library Manager**:
   - `FirebaseESP32` (by Mobizt)
   - `DHT sensor library` (by Adafruit)
   - `ArduinoJson`
3. WiFi and Firebase credentials are defined directly at the top of the `.ino` file — update them there with your own before uploading.
4. Select your ESP32 board, then upload the sketch.

### 3. Python agent

```bash
cd agent
pip install -r ../requirements.txt
cp ../Auth.env.example Auth.env   # fill in your credentials
python smai_agente.py
```

The agent needs an [OpenRouter](https://openrouter.ai) API key to query the LLM, and uses [ntfy.sh](https://ntfy.sh) for free push notifications (no account needed — just subscribe to the topic defined in `NTFY_TOPIC` inside the script).

### 4. Dashboard

```bash
cd dashboard
pip install -r ../requirements.txt
streamlit run smai_dashboard.py
```

`smai_dashboard.py` currently defines its Firebase connection details directly at the top of the script, so no `.env` file is required for it to run.

## Security notes

- `Auth.env` is excluded via `.gitignore` and should never be committed — only `Auth.env.example` is tracked.
- `smai_esp32.ino` and `smai_dashboard.py` currently contain their credentials directly in the source code rather than in an external config file. `.gitignore` cannot protect values that are hardcoded inside a tracked file, so if you fork or make this repository public, treat the API key, database URL, and passwords currently in those two files as exposed and rotate them.
- Firebase access is restricted by UID through `reglas_firebase.json`: only the ESP32 account can write sensor readings and irrigation status, and only the agent account can write recommendations.

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.
