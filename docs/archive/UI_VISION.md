# UI Vision & Roadmap

This document captures ideas and future direction for the Darkstar/Aurora User Interface.

## The "Cockpit" Philosophy
The Aurora UI should feel like a "Command Center" or "Cockpit" for an intelligent agent. It is not just a dashboard of static charts; it is a living interface that visualizes the AI's thought process, context, and decisions.

## Future Concepts (Brainstorming)

### 1. Interactive "What-If" Simulator
*   **Concept**: Allow the user to manipulate the forecast directly on the chart.
*   **Example**: Click and drag the load forecast to simulate "I'm charging the EV tonight."
*   **Goal**: See how the planner (Kepler) reacts in real-time. Does it buy more? Does it discharge less?

### 2. Voice/Chat Interface
*   **Concept**: A direct communication channel with Aurora within the Cockpit.
*   **Example**:
    *   *User*: "Why did you charge at 3 AM?"
    *   *Aurora*: "Prices were negative (-0.05 SEK) and you have a high load forecast for this morning."
*   **Goal**: Build trust by explaining "black box" decisions in natural language.

### 3. Live "Pulse" Visuals (Ambient Awareness)
*   **Concept**: Make the UI reflect the system's physical state and urgency.
*   **Example**:
    *   **Energy Flow**: Animated lines showing power moving from Grid -> Battery.
    *   **Price Alert**: The UI takes on a subtle red tint when prices are critically high.
    *   **Thinking**: A "brain activity" visual when the Strategy Engine is evaluating a new policy.

### 4. Gamification / "Thrift Score"
*   **Concept**: Quantify the value Aurora provides.
*   **Example**: "You saved **45 SEK** today by dodging the 18:00 price peak."
*   **Goal**: Reinforce the value of the system and encourage "good behavior" (e.g., shifting load).

### 5. Mobile Companion App
*   **Concept**: A simplified, read-only view for quick checks on the go.
*   **Features**: Current SoC, Next Action, Price Alert Push Notifications.
