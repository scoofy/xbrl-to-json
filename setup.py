import subprocess
import sys

def install(package):
    subprocess.call([sys.executable, "-m", "pip", "install", package])


dependencies = [
"bs4",
"anytree",
]
if __name__ == '__main__':
    for package in dependencies:
        install(package)