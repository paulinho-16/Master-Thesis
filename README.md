# Master Thesis

This repository contains the source code, documentation, and additional resources related to my Master's Thesis, developed for the Informatics and Computing Engineering (MEIC) course at the Faculty of Engineering of the University of Porto (FEUP).

This thesis was developed during the 5<sup>th</sup> year - 2<sup>nd</sup> semester and took place during the 2022/23 season.

The thesis document that describes the entire development of this tool can be found [here](docs/Master_Thesis.pdf), and the slides for my thesis presentation can be found [here](docs/Presentation.pdf).

## Table of Contents

- [Introduction](#introduction)
- [Usage](#usage)
- [Contributing](#contributing)
- [Acknowledgments](#acknowledgments)

## Introduction

This dissertation describes the development of a Modelling Methodology Towards Automated Generation of Road Network Digital Twins.

More specifically, it clarifies the development of a framework for the automatic creation of Digital Twins, which employs a generalised methodology applicable to any road network.

This framework was built on the microscopic simulator SUMO.

## Usage

Start by creating a Python virtual environment in Windows using the following commands:

```bash
1. py -m venv env
2. .\env\Scripts\activate.bat
3. pip install -r .\requirements.txt
```

Then, to run the program, the user can run the following commands:

`make`

- executes the framework in its entirety by sequentially executing the four framework phases.

`make prepare`

- initiates the first phase of the framework, which is responsible for preparing sensor data and helpful information for the subsequent phases.

`make variables`

- commences the second phase of the framework, which is responsible for assigning variables to the road network edges and deducing flow equations.

`make solve`

- executes the third phase of the framework, which solves the systems of linear equations derived in the previous phase, retrieving the free variables of the system and the pertinent matrices for its resolution.

`make run`

- initiates the fourth and ultimate phase of the framework, which involves the actual simulation of traffic on the road network selected by the user.

`make results`

- triggers the analysis of the outcomes produced by the simulation during the final phase of the framework, yielding the graphs to assess the framework’s performance.

`make clean`

- automatically cleans files generated during the project's execution, returning it to its initial state after deleting the produced outputs.

## Contributing

Feel free to contact me via email (pjsalgadomribeiro@gmail.com) if you experience any problems with this tool or would like to clarify any doubts about it.

## Acknowledgments

The baseline methodology of the developed framework was inspired by the work developed in the article "*Building a Motorway Digital Twin in SUMO: Real-Time Simulation of Continuous Data Stream from Traffic Counters*", whose source code can be found [here](https://github.com/SiLab-group/DigitalTwin_GenevaMotorway).
