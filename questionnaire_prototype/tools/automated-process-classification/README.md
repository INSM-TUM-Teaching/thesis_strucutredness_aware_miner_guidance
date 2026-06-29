# 🏛️ Automated Process Classification

![Automated Process Classification - Event Log Classifier](https://img.shields.io/badge/Automated%20Process%20Classification-Event%20Log%20Classifier-blue)
![Rust](https://img.shields.io/badge/Built%20with-Rust-orange?logo=rust)
![License](https://img.shields.io/badge/License-MIT-blue) <!-- Assuming MIT License -->

Automated Process Classification is a Rust-based application designed to analyze event logs in XES format. It processes these logs to discover dependencies between activities, generates a dependency matrix, and then classifies the overall process structure into categories such as Structured, Semi-Structured, Loosely Structured, or Unstructured.

The application offers both an interactive web-based user interface (built with Yew and WebAssembly) and a command-line interface (CLI) for versatile usage.

You can find a live demo of the web application at [https://insm-tum.github.io/automated-process-classification/](https://insm-tum.github.io/automated-process-classification/)

## ✨ Features

- **Import XES files** for event log analysis.
- **Classify event logs** into categories: Structured, Semi-Structured, Loosely Structured, Unstructured, or mixed classifications based on their discovered dependency matrix.
- **Adjustable thresholds** (0.0-1.0) for temporal and existential dependency discovery to fine-tune analysis and handle noisy logs.
- **Interactive web interface** for easy file uploading, threshold adjustment, and immediate visualization of classification results.
- **Command-Line Interface (CLI)** for automated processing, batch jobs, and integration into scripting workflows.
- **Output detailed dependency ratios** (CLI option) providing insights into the percentages of different dependency types (e.g., `none_none`, `eventual_implication`) found in the matrix, which underpin the classification.

## 🚀 Repository Overview
```
├── .github/workflows
│ └── continuous_deployment.yml # GitHub Actions workflow for deploying the web app
├── src
│ ├── classification.rs # Core logic for matrix classification based on dependency ratios
│ ├── dependency_types # Defines and discovers temporal/existential dependencies
│ │ ├── dependency.rs # General struct combining temporal and existential info
│ │ ├── existential.rs # Logic for existential dependency discovery
│ │ └── temporal.rs # Logic for temporal dependency discovery
│ ├── matrix_generation.rs # Generates dependency matrices from event log traces
│ ├── parser.rs # Parses XES files into structured traces
│ └── main.rs # Entry point for Web UI (Yew) and CLI (Clap)
├── Cargo.toml # Project dependencies and metadata
└── index.html # HTML entry point for the Yew web application
```


- `src/classification.rs`: Contains the `classify_matrix()` function. This is where the classification rules are applied to the percentages of various dependency types found in the matrix.
- `src/matrix_generation.rs`: Implements `generate_dependency_matrix()`, which takes parsed traces and thresholds to build the activity dependency matrix.
- `src/dependency_types/`:
    - `temporal.rs`: Contains `check_temporal_dependency()`, which discovers temporal relationships (Direct, Eventual) between activity pairs based on trace occurrences and a threshold.
    - `existential.rs`: Contains `check_existential_dependency()`, which discovers existential relationships (Implication, Equivalence, NegatedEquivalence) between activity pairs.
- `src/parser.rs`: Provides `parse_into_traces()` to read XES files (from path or content) and convert them into a list of activity sequences.
- `src/main.rs`: Orchestrates the application, handling CLI arguments via `clap` or launching the Yew web application.

## 🔧 Prerequisites

- **Rust and Cargo**: Install from [rustup.rs](https://rustup.rs/)
- **[Trunk](https://trunkrs.dev/)** (for Web UI development/local serving): A WASM web application bundler for Rust.
  ```sh
  cargo install trunk
  rustup target add wasm32-unknown-unknown
  ```

  ## 🚀 Getting Started

### 1. Clone the repository

```sh
git clone https://github.com/INSM-TUM/automated-process-classification.git
cd automated-process-classification
```

### 2. Start the web application (Optional)
If you wish to use the web interface locally:

```sh
trunk serve
```

Then, open your web browser and navigate to `http://localhost:8080/automated-process-classification/`.

> **Tips:** 
> - Use `trunk serve --open` to automatically open in your default browser
> - Specify a custom port with `trunk serve --port 1234`

### 3. Use the Command-Line Interface (CLI)

The application can be run directly from the command line.

First, ensure the project is built ( cargo run will do this automatically):

```sh
cargo build --release # Optional, for optimized binary
```

To run the CLI (examples):

```sh
# Using cargo run (compiles if needed):
# To pass arguments to the binary via 'cargo run', use '--'
cargo run -- --file-path path/to/your/log.xes

# Using the compiled binary (from target/release/ after `cargo build --release`):
./target/release/matrix_classifier --file-path path/to/your/log.xes
```

For a complete list of CLI options and their descriptions:
```sh
cargo run -- --help
```

## 📋 Usage Guide

### Web Interface

1. Upload XES File: Click the "Upload XES File" button (or the input field) and select an .xes file from your local system. The name of the selected file will appear.
2. Set Thresholds (Optional):
  * Temporal Threshold (0.0-1.0): Adjust this value to control the sensitivity of temporal dependency detection. A higher value means a temporal relationship must be observed more consistently across traces to be considered. Default is 1.0.
  * Existential Threshold (0.0-1.0): Adjust this value for existential dependency detection. Similar to the temporal threshold, it sets the minimum consistency required. Default is 1.0.
  * These thresholds should be set before clicking "Process Log". Invalid inputs (outside 0.0-1.0) will highlight the input box in red and disable the process button.
3. Process Log: Once a file is selected and thresholds are valid, click the "Process Log" button.
4. View Classification: The application will process the log and display the resulting classification (e.g., "Structured", "Semi-Structured", "Error: ...") below.

### Command-Line Interface (CLI)

The CLI is ideal for batch processing or integrating the classifier into automated workflows.

**Basic Classification:**
To classify an event log with default thresholds (1.0 for both):

```sh
cargo run -- --file-path /path/to/your/event_log.xes
# or
# ./target/release/matrix_classifier --file-path /path/to/your/event_log.xes
```

Output (ClassificationType is a placeholder, in reality it will be something like "Structured" or "SemiStructured" etc.):
```
Classification Result: <ClassificationType>
```

**Specifying Thresholds:**
You can override the default temporal and existential thresholds:
```sh
cargo run -- --file-path log.xes \
             --temporal-threshold 0.85 \
             --existential-threshold 0.90
```

**Printing Dependency Ratios:**
To get a more detailed breakdown of the dependency types found in the matrix (which are used for classification), use the --print-ratios flag:
```sh
cargo run -- --file-path log.xes --print-ratios
```

**Getting Help:**
For a full list of available commands and options:
```sh
cargo run -- --help
# or
# ./target/release/matrix_classifier --help
```

| Dependency | Purpose |
|------------|---------|
| [Yew](https://yew.rs/) | Modern Rust framework for front-end web apps using WebAssembly |
| [wasm-bindgen](https://rustwasm.github.io/wasm-bindgen/) | High-level interactions between Rust and JavaScript |
| [web-sys](https://rustwasm.github.io/wasm-bindgen/web-sys/) | Bindings for Web APIs |
| [process_mining](https://crates.io/crates/process_mining) | Process mining library for Rust |
| [clap](https://crates.io/crates/clap) | A popular and feature-rich command Line Argument Parser for Rust. |
| [chrono](https://crates.io/crates/chrono) | Date and time library for Rust, used for handling timestamps in event logs. |
| [serde](https://crates.io/crates/serde) | A framework for serializing and deserializing Rust data structures efficiently. |

## 📜 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## 👏 Acknowledgments

- Thanks to the contributors of the Rust and Yew communities for their support and tools
