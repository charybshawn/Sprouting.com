#!/bin/bash

# Colors for better readability
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Sprouting.com Scraper Setup ===${NC}"

# Check if Python is installed
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo -e "${RED}Error: Python is not installed. Please install Python 3.7+ and try again.${NC}"
    exit 1
fi

# Check Python version
PYTHON_VERSION=$($PYTHON_CMD -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ $PYTHON_MAJOR -lt 3 ] || ([ $PYTHON_MAJOR -eq 3 ] && [ $PYTHON_MINOR -lt 7 ]); then
    echo -e "${RED}Error: Python 3.7+ is required. You have Python $PYTHON_VERSION.${NC}"
    exit 1
fi

echo -e "${GREEN}Using Python $PYTHON_VERSION${NC}"

# Ask about virtual environment
read -p "Do you want to create a virtual environment? (y/n) " CREATE_VENV
if [[ $CREATE_VENV == "y" || $CREATE_VENV == "Y" ]]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    
    # Check if venv module is available
    if ! $PYTHON_CMD -c "import venv" &>/dev/null; then
        echo -e "${RED}Error: venv module not available. Install python3-venv package for your distribution.${NC}"
        exit 1
    fi
    
    # Create venv
    $PYTHON_CMD -m venv venv
    
    # Activate venv
    if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
        # Windows
        source venv/Scripts/activate
    else
        # Unix-like
        source venv/bin/activate
    fi
    
    echo -e "${GREEN}Virtual environment created and activated.${NC}"
    PYTHON_CMD="python"  # Inside venv, python points to the right version
fi

# Install Python packages
echo -e "${YELLOW}Installing required Python packages...${NC}"
$PYTHON_CMD -m pip install --upgrade pip
$PYTHON_CMD -m pip install -r requirements.txt

if [ $? -ne 0 ]; then
    echo -e "${RED}Error installing Python packages. Check the error message above.${NC}"
    exit 1
fi

# Install Playwright browsers
echo -e "${YELLOW}Installing Playwright browsers...${NC}"
$PYTHON_CMD -m playwright install chromium

if [ $? -ne 0 ]; then
    echo -e "${RED}Error installing Playwright browsers. Check the error message above.${NC}"
    exit 1
fi

echo -e "${GREEN}Setup completed successfully!${NC}"
echo -e "${YELLOW}To run the scraper:${NC}"
if [[ $CREATE_VENV == "y" || $CREATE_VENV == "Y" ]]; then
    echo "  1. Activate the virtual environment:"
    if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
        echo "     source venv/Scripts/activate"
    else
        echo "     source venv/bin/activate"
    fi
    echo "  2. Run the scraper:"
fi
echo "     python sprouting_scraper.py"
echo
echo -e "${YELLOW}To use the selector helper:${NC}"
echo "     python selector_helper.py URL"
echo
echo -e "${YELLOW}To analyze scraped data:${NC}"
echo "     python analyze_products.py" 