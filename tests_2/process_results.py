import os
import json
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

def analyze_performance_data():
    """
    Analyzes performance data from JSON files, calculates statistics,
    and generates plots.
    """
    results_dir = Path('.')
    plot_dir = results_dir / 'graficos'
    plot_dir.mkdir(exist_ok=True)

    # Find all individual result files
    json_files = list(results_dir.glob('test_run_*/*.json'))
    json_files = [f for f in json_files if f.name != 'all_results.json']

    # Group files by scenario
    scenarios = {}
    for f in json_files:
        scenario_name = f.name.replace('.json', '')
        if scenario_name not in scenarios:
            scenarios[scenario_name] = []
        scenarios[scenario_name].append(f)

    # Process each scenario
    all_stats = []
    for scenario_name, files in scenarios.items():
        scenario_metrics = {
            'avg_fps': [],
            'avg_latency': [],
            'total_events': [],
            'cpu_avg': [],
            'ram_avg': [],
            'gpu_avg': [],
            'vram_avg': [],
        }

        for file_path in files:
            with open(file_path, 'r') as f:
                data = json.load(f)
                app_metrics = data.get('app', {})
                system_metrics = data.get('system', {})

                scenario_metrics['avg_fps'].append(app_metrics.get('avg_fps', 0))
                scenario_metrics['avg_latency'].append(app_metrics.get('avg_latency', 0))
                scenario_metrics['total_events'].append(app_metrics.get('total_events', 0))
                scenario_metrics['cpu_avg'].append(system_metrics.get('cpu_avg', 0))
                scenario_metrics['ram_avg'].append(system_metrics.get('ram_avg', 0))
                scenario_metrics['gpu_avg'].append(system_metrics.get('gpu_avg', 0))
                scenario_metrics['vram_avg'].append(system_metrics.get('vram_avg', 0))

        # Calculate stats
        stats = {'scenario': scenario_name}
        for metric, values in scenario_metrics.items():
            stats[f'{metric}_mean'] = np.mean(values)
            stats[f'{metric}_std'] = np.std(values)
            stats[f'{metric}_median'] = np.median(values)
        
        # Add config details
        if files:
            with open(files[0], 'r') as f:
                data = json.load(f)
                config = data.get('config', {})
                stats['cameras'] = config.get('cameras')
                stats['fps'] = config.get('fps')
                stats['model'] = config.get('model', 'unknown').replace('.pt', '')

        all_stats.append(stats)

    df = pd.DataFrame(all_stats)
    
    # Save stats to CSV
    df.to_csv('performance_summary.csv', index=False)
    print("Performance summary saved to performance_summary.csv")

    # Generate plots
    generate_plots(df, plot_dir)

def generate_plots(df, plot_dir):
    """Generates and saves plots for each FPS value."""
    
    if df.empty:
        print("No data to plot.")
        return

    models = sorted([m for m in df['model'].unique() if m != 'unknown'])
    fps_values = sorted(df['fps'].unique())
    
    if not models:
        print("Could not determine models from data. Skipping plot generation.")
        return
    if not fps_values:
        print("Could not determine FPS values from data. Skipping plot generation.")
        return

    for fps in fps_values:
        fps_df = df[df['fps'] == fps]
        
        # Plotting helper function
        def create_plot(metric, y_label, title, filename):
            if metric not in df.columns:
                return
            
            plt.figure(figsize=(10, 6))
            for model in models:
                model_df = fps_df[fps_df['model'] == model].groupby('cameras')[metric].mean().reset_index()
                if not model_df.empty:
                    plt.plot(model_df['cameras'], model_df[metric], marker='o', linestyle='-', label=model)
            
            plt.xlabel('Number of Cameras')
            plt.ylabel(y_label)
            plt.title(f'{title} ({fps} FPS Setting)')
            plt.legend()
            plt.grid(True)
            plt.xticks(sorted(fps_df['cameras'].unique()))
            plot_filename = plot_dir / f'{filename}_{fps}fps.png'
            plt.savefig(plot_filename)
            plt.close()
            print(f"Saved plot: {plot_filename.name}")

        create_plot('avg_fps_mean', 'Average FPS', 'Average FPS vs. Number of Cameras', 'avg_fps_vs_cameras')
        create_plot('avg_latency_mean', 'Average Latency (ms)', 'Average Latency vs. Number of Cameras', 'avg_latency_vs_cameras')
        create_plot('gpu_avg_mean', 'Average GPU Usage (%)', 'Average GPU Usage vs. Number of Cameras', 'gpu_usage_vs_cameras')
        create_plot('vram_avg_mean', 'Average VRAM Usage (%)', 'Average VRAM Usage vs. Number of Cameras', 'vram_usage_vs_cameras')
        create_plot('ram_avg_mean', 'Average RAM Usage (%)', 'Average RAM Usage vs. Number of Cameras', 'ram_usage_vs_cameras')
        create_plot('cpu_avg_mean', 'Average CPU Usage (%)', 'Average CPU Usage vs. Number of Cameras', 'cpu_usage_vs_cameras')

    # --- Plot 4: Resource Usage for a high-load scenario ---
    # Find the scenario with the highest camera count, then highest FPS, then largest model
    if not df.empty:
        df['model_size'] = df['model'].apply(lambda x: {'yolov8n': 0, 'yolov8s': 1, 'yolov8m': 2}.get(x, -1))
        high_load_scenario = df.sort_values(['cameras', 'fps', 'model_size'], ascending=[False, False, False]).iloc[0]
        
        metrics = ['cpu_avg_mean', 'ram_avg_mean', 'gpu_avg_mean', 'vram_avg_mean']
        labels = ['CPU', 'RAM', 'GPU', 'VRAM']
        
        values = []
        metric_labels = []
        for metric, label in zip(metrics, labels):
            if metric in high_load_scenario and pd.notna(high_load_scenario[metric]) and high_load_scenario[metric] > 0:
                values.append(high_load_scenario[metric])
                metric_labels.append(label)

        if values:
            plt.figure(figsize=(8, 5))
            plt.bar(metric_labels, values, color=['skyblue', 'lightgreen', 'salmon', 'gold'])
            plt.ylabel('Average Usage (%)')
            scenario_title = (f"Highest Load: {high_load_scenario['cameras']} Cams, "
                              f"{high_load_scenario['fps']} FPS, {high_load_scenario['model']}")
            plt.title(scenario_title)
            for i, v in enumerate(values):
                plt.text(i, v + 1, f"{v:.2f}%", ha='center')
            
            plt.ylim(0, max(values) + 10 if values else 10)
            plot_filename = plot_dir / 'high_load_resource_usage.png'
            plt.savefig(plot_filename)
            plt.close()
            print(f"Saved plot: {plot_filename.name}")




if __name__ == "__main__":
    try:
        analyze_performance_data()
    except ImportError as e:
        print(f"Error: Missing dependency - {e.name}")
        print("Please install the required libraries: pip install pandas matplotlib numpy")

