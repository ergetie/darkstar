```mermaid
graph TD
    subgraph "1. Data Gathering (inputs.py)"
        A[Nordpool Prices] --> C;
        B[Weather Forecast] --> C;
        D[Home Assistant Sensors] --> C;
    end

    subgraph "2. Planning (planner.py)"
        C[Raw Data] --> E{Planner};
        E -- Creates Plan --> F[Energy Schedule];
        J[s-index / Safety Buffer] --> E;
    end

    subgraph "3. Execution & Storage"
        F --> G[Web UI (webapp.py)];
        F --> H{Databases};
    end

    subgraph "4. Learning (learning.py)"
        H --> I[Learning Engine];
        I -- Analyzes Past Performance --> J;
    end

    style A fill:#D4E6F1,stroke:#1B4F72
    style B fill:#D4E6F1,stroke:#1B4F72
    style D fill:#D4E6F1,stroke:#1B4F72
    style G fill:#D5F5E3,stroke:#186A3B
```
