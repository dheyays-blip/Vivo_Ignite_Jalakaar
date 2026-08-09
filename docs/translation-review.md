# Jalaakar — translation review sheet

**For a native Marathi and Hindi reader. Please read every string below.**

This is Phase 8 item 8.2 on the prototype checklist and it is the one thing
in the build that cannot be verified by a test. These strings are sent to
farmers and housing societies as water warnings. A wrong word here is worse
than no alert at all.

**What we need from you, per string:**

1. Is it correct Marathi / Hindi, not translated-sounding English?
2. Would a farmer or a society secretary understand it immediately?
3. Is the tone right — urgent without panic, respectful without being formal?
4. Do the technical words (जल तनाव, भूजल, ठिबक) read naturally?

Mark each ✅ ok, ✏️ reword, or ❌ wrong, and write the correction inline.

Placeholders in `{braces}` are filled at send time — leave them exactly as they are.

_Generated 08 Aug 2026 from the running code._

---

## 1. Alert messages

Sent over WhatsApp when a score crosses into MONITOR or ACT NOW. SAFE messages are only sent if explicitly requested.

### Farmer / villager

#### CRITICAL — act now

**English (reference — this one is already fine):**

```
JALAAKAR ALERT — {place}
Water stress score: {score}/100 (Critical)
Your well could run dry in about {days} days.

Do this now:
• Switch to drip irrigation
• Choose a low-water crop
• Check for leaks

Reply HELP for support.
```

**मराठी Marathi** — ⬜ ok / ⬜ reword / ⬜ wrong

```
जलाकार इशारा — {place}
पाणी ताण गुण: {score}/100 (गंभीर)
अंदाजे {days} दिवसांत विहीर आटू शकते.

आजच करा:
• ठिबक सिंचनावर जा
• कमी पाण्याचे पीक निवडा
• गळती तपासा

मदतीसाठी HELP पाठवा.
```

**हिंदी Hindi** — ⬜ ok / ⬜ reword / ⬜ wrong

```
जलाकार चेतावनी — {place}
जल तनाव स्कोर: {score}/100 (गंभीर)
लगभग {days} दिनों में कुआँ सूख सकता है।

आज ही करें:
• ड्रिप सिंचाई अपनाएँ
• कम पानी वाली फसल चुनें
• रिसाव जाँचें

मदद के लिए HELP भेजें।
```

#### Monitor

**English (reference — this one is already fine):**

```
JALAAKAR NOTICE — {place}
Water stress score: {score}/100 (Monitor)
Levels are falling. Reduce usage where you can.
Reply BOOK for a rainwater harvesting workshop.
```

**मराठी Marathi** — ⬜ ok / ⬜ reword / ⬜ wrong

```
जलाकार सूचना — {place}
पाणी ताण गुण: {score}/100 (लक्ष ठेवा)
पाणी पातळी घटत आहे. वापर कमी करा.
पाणी साठवण कार्यशाळेसाठी BOOK पाठवा.
```

**हिंदी Hindi** — ⬜ ok / ⬜ reword / ⬜ wrong

```
जलाकार सूचना — {place}
जल तनाव स्कोर: {score}/100 (निगरानी रखें)
जल स्तर घट रहा है। उपयोग कम करें।
जल संचयन कार्यशाला हेतु BOOK भेजें।
```

#### All clear

**English (reference — this one is already fine):**

```
JALAAKAR — {place}
Water stress score: {score}/100 (Safe)
No action needed. Next forecast in 30 days.
```

**मराठी Marathi** — ⬜ ok / ⬜ reword / ⬜ wrong

```
जलाकार — {place}
पाणी ताण गुण: {score}/100 (सुरक्षित)
सध्या धोका नाही. पुढील अंदाज ३० दिवसांत.
```

**हिंदी Hindi** — ⬜ ok / ⬜ reword / ⬜ wrong

```
जलाकार — {place}
जल तनाव स्कोर: {score}/100 (सुरक्षित)
अभी कोई खतरा नहीं। अगला पूर्वानुमान 30 दिनों में।
```

### Housing society

#### CRITICAL — act now

**English (reference — this one is already fine):**

```
JALAAKAR ALERT — {place}
Water stress score: {score}/100 (Critical)
Storage {level}. About {days} days of supply left.

Do this now:
• Book tankers early — emergency rate is ₹3,000
• Check the society for leaks
• Notify residents
```

**मराठी Marathi** — ⬜ ok / ⬜ reword / ⬜ wrong

```
जलाकार इशारा — {place}
पाणी ताण गुण: {score}/100 (गंभीर)
साठा {level}. सुमारे {days} दिवस पुरेल.

आजच करा:
• टँकर आधीच बुक करा (आणीबाणीत ₹3,000)
• गळती तपासा
• रहिवाशांना कळवा
```

**हिंदी Hindi** — ⬜ ok / ⬜ reword / ⬜ wrong

```
जलाकार चेतावनी — {place}
जल तनाव स्कोर: {score}/100 (गंभीर)
भंडार {level}. लगभग {days} दिन चलेगा।

आज ही करें:
• टैंकर पहले से बुक करें (आपात दर ₹3,000)
• रिसाव जाँचें
• निवासियों को सूचित करें
```

#### Monitor

**English (reference — this one is already fine):**

```
JALAAKAR NOTICE — {place}
Water stress score: {score}/100 (Monitor)
Storage {level}. Start planning now, not later.
```

**मराठी Marathi** — ⬜ ok / ⬜ reword / ⬜ wrong

```
जलाकार सूचना — {place}
पाणी ताण गुण: {score}/100 (लक्ष ठेवा)
साठा {level}. आतापासून नियोजन करा.
```

**हिंदी Hindi** — ⬜ ok / ⬜ reword / ⬜ wrong

```
जलाकार सूचना — {place}
जल तनाव स्कोर: {score}/100 (निगरानी रखें)
भंडार {level}. अभी से योजना बनाएँ।
```

#### All clear

**English (reference — this one is already fine):**

```
JALAAKAR — {place}
Water stress score: {score}/100 (Safe)
Storage {level}. No tanker planning needed right now.
```

**मराठी Marathi** — ⬜ ok / ⬜ reword / ⬜ wrong

```
जलाकार — {place}
पाणी ताण गुण: {score}/100 (सुरक्षित)
साठा {level}. सध्या टँकरची गरज नाही.
```

**हिंदी Hindi** — ⬜ ok / ⬜ reword / ⬜ wrong

```
जलाकार — {place}
जल तनाव स्कोर: {score}/100 (सुरक्षित)
भंडार {level}. अभी टैंकर की ज़रूरत नहीं।
```

---

## 2. WhatsApp conversation replies

The Jal Mitra flow: a volunteer sends their borewell depth and gets these back.

### Asking which village (first contact)  `ask_place`

**English:**

```
Welcome to Jalaakar. Which village or taluka is your well in?
```

**मराठी** — ⬜ ok / ⬜ reword / ⬜ wrong

```
जलाकार मध्ये स्वागत. तुमची विहीर कोणत्या गावात किंवा तालुक्यात आहे?
```

**हिंदी** — ⬜ ok / ⬜ reword / ⬜ wrong

```
जलाकार में स्वागत है। आपका कुआँ किस गाँव या तालुका में है?
```

### Asking for the depth  `ask_depth`

**English:**

```
Got it — {place}. How many METRES is the water below ground? Reply with just the number.
```

**मराठी** — ⬜ ok / ⬜ reword / ⬜ wrong

```
{place} नोंदवले. पाणी जमिनीपासून किती मीटर खाली आहे? फक्त आकडा पाठवा.
```

**हिंदी** — ⬜ ok / ⬜ reword / ⬜ wrong

```
{place} दर्ज किया। पानी ज़मीन से कितने मीटर नीचे है? सिर्फ़ संख्या भेजें।
```

### Reading accepted  `accepted`

**English:**

```
Recorded: {level} m at {place}. Thank you — this is the freshest reading we have there. Reply SCORE for your water stress score.
```

**मराठी** — ⬜ ok / ⬜ reword / ⬜ wrong

```
नोंद: {place} येथे {level} मी. धन्यवाद — तिथली ही सर्वात ताजी नोंद आहे. गुणांसाठी SCORE पाठवा.
```

**हिंदी** — ⬜ ok / ⬜ reword / ⬜ wrong

```
दर्ज: {place} पर {level} मी. धन्यवाद — यह वहाँ की सबसे नई रीडिंग है। स्कोर के लिए SCORE भेजें।
```

### Reading looks unusual — held for checking  `flagged`

**English:**

```
Recorded {level} m, but it is well outside the usual range here, so we are holding it for checking. If it is right, send it again tomorrow and we will trust it.
```

**मराठी** — ⬜ ok / ⬜ reword / ⬜ wrong

```
{level} मी नोंदवले, पण ते इथल्या नेहमीच्या पातळीपेक्षा खूप वेगळे आहे. तपासणीसाठी ठेवले आहे. बरोबर असल्यास उद्या पुन्हा पाठवा.
```

**हिंदी** — ⬜ ok / ⬜ reword / ⬜ wrong

```
{level} मी दर्ज, पर यह यहाँ की सामान्य सीमा से बहुत बाहर है, इसलिए जाँच हेतु रोका गया है। सही हो तो कल दोबारा भेजें।
```

### Reading rejected  `rejected`

**English:**

```
That does not look right: {reason} Please check and send again.
```

**मराठी** — ⬜ ok / ⬜ reword / ⬜ wrong

```
हे बरोबर वाटत नाही: {reason} कृपया तपासून पुन्हा पाठवा.
```

**हिंदी** — ⬜ ok / ⬜ reword / ⬜ wrong

```
यह सही नहीं लगता: {reason} कृपया जाँचकर दोबारा भेजें।
```

### HELP menu  `help`

**English:**

```
Jalaakar: send a NUMBER for your borewell depth in metres. SCORE for your water stress score. BOOK for a workshop. STOP to unsubscribe.
```

**मराठी** — ⬜ ok / ⬜ reword / ⬜ wrong

```
जलाकार: विहिरीची खोली मीटरमध्ये आकड्याने पाठवा. SCORE = पाणी ताण गुण. BOOK = कार्यशाळा. STOP = थांबवा.
```

**हिंदी** — ⬜ ok / ⬜ reword / ⬜ wrong

```
जलाकार: कुएँ की गहराई मीटर में संख्या भेजें। SCORE = जल तनाव स्कोर। BOOK = कार्यशाला। STOP = बंद करें।
```

### Village not recognised  `unknown_place`

**English:**

```
I could not find that place in the CGWB well network. Try the taluka name, for example: Baglan
```

**मराठी** — ⬜ ok / ⬜ reword / ⬜ wrong

```
ते ठिकाण CGWB विहीर जाळ्यात सापडले नाही. तालुक्याचे नाव पाठवा, उदा: Baglan
```

**हिंदी** — ⬜ ok / ⬜ reword / ⬜ wrong

```
वह स्थान CGWB कुआँ नेटवर्क में नहीं मिला। तालुका नाम भेजें, जैसे: Baglan
```

### Their current stress score  `score`

**English:**

```
{place} — water stress {score}/100, {band}. Based on readings up to {date}. Send your borewell depth as a number to sharpen it.
```

**मराठी** — ⬜ ok / ⬜ reword / ⬜ wrong

```
{place} — पाणी ताण {score}/100, {band}. {date} पर्यंतच्या नोंदींवर आधारित. अचूकतेसाठी विहिरीची खोली आकड्याने पाठवा.
```

**हिंदी** — ⬜ ok / ⬜ reword / ⬜ wrong

```
{place} — जल तनाव {score}/100, {band}. {date} तक की रीडिंग पर आधारित। सटीकता हेतु कुएँ की गहराई संख्या में भेजें।
```

### Not enough data for their area  `no_score`

**English:**

```
We do not have enough readings for your area yet. Send your borewell depth as a number and we will start building it.
```

**मराठी** — ⬜ ok / ⬜ reword / ⬜ wrong

```
तुमच्या भागासाठी पुरेशा नोंदी नाहीत. विहिरीची खोली आकड्याने पाठवा.
```

**हिंदी** — ⬜ ok / ⬜ reword / ⬜ wrong

```
आपके क्षेत्र हेतु पर्याप्त रीडिंग नहीं हैं। कुएँ की गहराई संख्या में भेजें।
```

### Workshop menu  `book`

**English:**

```
Workshops: rainwater harvesting, groundwater recharge, leak detection. Reply with the number 1, 2 or 3 and we will call you.
```

**मराठी** — ⬜ ok / ⬜ reword / ⬜ wrong

```
कार्यशाळा: जलसंधारण, भूजल पुनर्भरण, गळती शोध. 1, 2 किंवा 3 पाठवा, आम्ही संपर्क करू.
```

**हिंदी** — ⬜ ok / ⬜ reword / ⬜ wrong

```
कार्यशालाएँ: वर्षा जल संचयन, भूजल पुनर्भरण, रिसाव पहचान. 1, 2 या 3 भेजें, हम संपर्क करेंगे।
```

### Workshop confirmed  `booked`

**English:**

```
Booked: {topic}. Someone will call you within two working days.
```

**मराठी** — ⬜ ok / ⬜ reword / ⬜ wrong

```
नोंदणी झाली: {topic}. दोन कामकाजाच्या दिवसांत संपर्क केला जाईल.
```

**हिंदी** — ⬜ ok / ⬜ reword / ⬜ wrong

```
बुक हुआ: {topic}. दो कार्य दिवसों में संपर्क किया जाएगा।
```

### Unsubscribed  `stopped`

**English:**

```
You will get no more Jalaakar alerts. Send START to resume.
```

**मराठी** — ⬜ ok / ⬜ reword / ⬜ wrong

```
यापुढे जलाकार सूचना येणार नाहीत. पुन्हा सुरू करण्यासाठी START पाठवा.
```

**हिंदी** — ⬜ ok / ⬜ reword / ⬜ wrong

```
अब जलाकार अलर्ट नहीं आएँगे। दोबारा शुरू करने हेतु START भेजें।
```

---

## 3. Stress band labels

These appear on the score card itself.

| Band | English | मराठी | हिंदी | ⬜ |
|---|---|---|---|---|
| SAFE | Safe | सुरक्षित | सुरक्षित | ⬜ |
| MONITOR | Monitor | लक्ष ठेवा | निगरानी रखें | ⬜ |
| ACT NOW | Act now | त्वरित कृती | तुरंत कार्रवाई | ⬜ |

---

## 4. Workshop names

| # | English | मराठी | हिंदी | ⬜ |
|---|---|---|---|---|
| 1 | rainwater harvesting | जलसंधारण | वर्षा जल संचयन | ⬜ |
| 2 | groundwater recharge | भूजल पुनर्भरण | भूजल पुनर्भरण | ⬜ |
| 3 | leak detection | गळती शोध | रिसाव पहचान | ⬜ |

---

## Where to apply corrections

- Alert messages → `api/alerts.py`, `TEMPLATES`
- Conversation replies → `api/community.py`, `REPLIES`
- Band labels → `api/scoring.py`, `BAND_LABELS`
- Workshop names → `api/community.py`, `WORKSHOPS`

After editing, run `python api/test_smoke.py` — 47 checks, none of which
depend on the wording, so a translation fix cannot break the build.
