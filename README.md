# Order a pizza
A simple implementation of an autonomous web browsing agent.

Originally presented in at the [AI Camp Meetup](https://www.linkedin.com/feed/update/urn:li:activity:7171609373138411520/) in SF on March 6, 2024.
- [Video recording](https://youtu.be/1xlABlYnxSQ?si=6-s5IbSKCzhtiYOy&t=2402)
- [Presentation slides](https://docs.google.com/presentation/d/1OkrKJCw-vqkCIeiSP-13K8XKeuKSV7tfGsVc5BI1-4A/edit?usp=sharing)

<img src="https://github.com/ericdjiang/order-a-pizza/assets/20948797/54dd9524-ae05-462f-838e-7d3dcef605c6" width="250" height="250"/>

# Getting started
The notebook `playground.ipynb` is powered by [Solar](https://www.upstage.ai/feed/press/solar-api-beta), a state-of-the-art lightweight model that ranks at the top of open LLM eval leaderboards.

The Solar API is in free beta right now, and is super easy to get started! Grab a token [here](https://www.upstage.ai/?utm_term=Solar+LLM&utm_content=%2Fgnb#solar-llm)

Create a `.env` file with your LLM API Keys
```
SOLAR_API_KEY=<...>
GEMINI_PRO_API_KEY=<...>
OPENAI_API_KEY=<...>
```

Install the requirements
```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

At this point you should be able open the notebook `playground.ipynb` in VS Code. Make sure the Python interpreter is pointing to `.venv`.

To run the full agent: `python agent.py`

## Disclaimer
This is super WIP right now! The code is all over the place and messy, and I will get it cleaned up and add a formal README with setup instructions over the weekend (by 03/10).

If you have any questions / want to contribute, would love to chat!

My Linkedin: https://www.linkedin.com/in/ericdjiang/
