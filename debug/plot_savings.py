import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd


def main():
    df = pd.read_csv("benchmark_results.csv")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")

    df["cumulative_savings"] = df["savings"].cumsum()

    plt.figure(figsize=(12, 6))
    plt.plot(
        df["date"],
        df["cumulative_savings"],
        label="Cumulative Savings (SEK)",
        color="green",
        linewidth=2,
    )
    plt.fill_between(df["date"], df["cumulative_savings"], alpha=0.3, color="green")

    plt.title("Kepler vs Legacy MPC: Cumulative Savings (30 Days)")
    plt.ylabel("Savings (SEK)")
    plt.xlabel("Date")
    plt.grid(True, alpha=0.3)
    plt.legend()

    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    plt.gca().xaxis.set_major_locator(mdates.DayLocator(interval=2))
    plt.gcf().autofmt_xdate()

    plt.tight_layout()
    plt.savefig("benchmark_savings_plot.png")
    print("Saved benchmark_savings_plot.png")


if __name__ == "__main__":
    main()
