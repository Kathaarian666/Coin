// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

// Test-only contracts used by tests/test_honeypot_evm.py on a local EVM.

contract MockWETH {
    mapping(address => uint256) public balanceOf;

    function deposit() external payable {
        balanceOf[msg.sender] += msg.value;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
        return true;
    }
}

interface IBal {
    function balanceOf(address) external view returns (uint256);
    function transfer(address, uint256) external returns (bool);
}

// Minimal Uniswap V2 pair: same swap/K semantics with a 0.3% fee.
contract MockPair {
    address public token0;
    address public token1;
    uint112 private reserve0;
    uint112 private reserve1;

    constructor(address a, address b) {
        (token0, token1) = a < b ? (a, b) : (b, a);
    }

    function getReserves() external view returns (uint112, uint112, uint32) {
        return (reserve0, reserve1, 0);
    }

    function sync() public {
        reserve0 = uint112(IBal(token0).balanceOf(address(this)));
        reserve1 = uint112(IBal(token1).balanceOf(address(this)));
    }

    function swap(uint256 out0, uint256 out1, address to, bytes calldata) external {
        require(out0 < reserve0 && out1 < reserve1, "LIQ");
        if (out0 > 0) require(IBal(token0).transfer(to, out0), "T0");
        if (out1 > 0) require(IBal(token1).transfer(to, out1), "T1");
        uint256 b0 = IBal(token0).balanceOf(address(this));
        uint256 b1 = IBal(token1).balanceOf(address(this));
        uint256 in0 = b0 > reserve0 - out0 ? b0 - (reserve0 - out0) : 0;
        uint256 in1 = b1 > reserve1 - out1 ? b1 - (reserve1 - out1) : 0;
        require(in0 > 0 || in1 > 0, "IN");
        uint256 a0 = b0 * 1000 - in0 * 3;
        uint256 a1 = b1 * 1000 - in1 * 3;
        require(a0 * a1 >= uint256(reserve0) * reserve1 * 1e6, "K");
        reserve0 = uint112(b0);
        reserve1 = uint112(b1);
    }
}

// ERC-20 with configurable taxes and a sell block, mimicking scam tokens.
contract TaxToken {
    mapping(address => uint256) public balanceOf;
    mapping(address => bool) public blacklisted;
    uint256 public totalSupply;
    address public owner;
    address public pair;
    uint256 public buyTaxBps;
    uint256 public sellTaxBps;
    bool public sellsBlocked;

    constructor(uint256 supply) {
        owner = msg.sender;
        totalSupply = supply;
        balanceOf[msg.sender] = supply;
    }

    function configure(address pair_, uint256 buyTax, uint256 sellTax, bool blockSells) external {
        require(msg.sender == owner);
        pair = pair_;
        buyTaxBps = buyTax;
        sellTaxBps = sellTax;
        sellsBlocked = blockSells;
    }

    function mint(address to, uint256 amount) external {
        require(msg.sender == owner);
        balanceOf[to] += amount;
        totalSupply += amount;
    }

    function setBlacklist(address who, bool value) external {
        require(msg.sender == owner);
        blacklisted[who] = value;
    }

    function renounceOwnership() external {
        require(msg.sender == owner);
        owner = address(0);
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        require(!blacklisted[msg.sender], "BL");
        uint256 tax;
        if (msg.sender == pair) tax = amount * buyTaxBps / 10000;
        if (to == pair && msg.sender != owner) {
            require(!sellsBlocked, "SELL");
            tax = amount * sellTaxBps / 10000;
        }
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount - tax;
        balanceOf[owner] += tax;
        return true;
    }
}
