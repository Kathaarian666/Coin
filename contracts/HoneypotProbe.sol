// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

// Simulates a buy and a sell against a Uniswap V2 style pair.
// Never deployed: the scanner injects this runtime code at a throwaway address
// through an eth_call state override, so the simulation costs nothing.

interface IERC20Min {
    function balanceOf(address) external view returns (uint256);
}

interface IWETHMin {
    function deposit() external payable;
    function transfer(address, uint256) external returns (bool);
}

interface IPairMin {
    function token0() external view returns (address);
    function getReserves() external view returns (uint112, uint112, uint32);
    function swap(uint256, uint256, address, bytes calldata) external;
}

contract HoneypotProbe {
    struct Result {
        uint256 buyRequested; // tokens asked from the pair
        uint256 buyReceived;  // tokens that actually arrived (difference = buy tax)
        uint256 sellSent;     // tokens sent back to the pair
        uint256 sellArrived;  // tokens the pair actually got (difference = sell tax)
        uint256 wethOut;      // WETH received for the sell
        uint8 failedStage;    // 0 ok, 1 buy swap, 2 sell transfer, 3 sell swap
    }

    // feeBps is deliberately conservative (e.g. 100 = 1%) so forks with a
    // higher swap fee than Uniswap's 0.3% still pass the pair's K check.
    function probe(address pair, address token, address weth, uint256 amountIn, uint256 feeBps)
        external
        returns (Result memory r)
    {
        IWETHMin(weth).deposit{value: amountIn}();
        bool tokenIs0 = IPairMin(pair).token0() == token;

        (uint256 rToken, uint256 rWeth) = _reserves(pair, tokenIs0);
        r.buyRequested = _amountOut(amountIn, rWeth, rToken, feeBps);
        IWETHMin(weth).transfer(pair, amountIn);

        uint256 before = IERC20Min(token).balanceOf(address(this));
        try IPairMin(pair).swap(tokenIs0 ? r.buyRequested : 0, tokenIs0 ? 0 : r.buyRequested, address(this), "") {}
        catch {
            r.failedStage = 1;
            return r;
        }
        r.buyReceived = IERC20Min(token).balanceOf(address(this)) - before;
        if (r.buyReceived == 0) {
            r.failedStage = 1;
            return r;
        }

        r.sellSent = r.buyReceived;
        uint256 pairBefore = IERC20Min(token).balanceOf(pair);
        (bool ok, bytes memory data) =
            token.call(abi.encodeWithSelector(0xa9059cbb, pair, r.sellSent));
        if (!ok || (data.length > 0 && !abi.decode(data, (bool)))) {
            r.failedStage = 2;
            return r;
        }
        r.sellArrived = IERC20Min(token).balanceOf(pair) - pairBefore;

        // Reserves are re-read after the transfer: tax tokens often swap their
        // collected fees through the same pair inside transfer().
        (rToken, rWeth) = _reserves(pair, tokenIs0);
        uint256 pairTokens = IERC20Min(token).balanceOf(pair);
        uint256 amountInSell = pairTokens > rToken ? pairTokens - rToken : 0;
        uint256 out = _amountOut(amountInSell, rToken, rWeth, feeBps);
        if (out == 0) {
            r.failedStage = 3;
            return r;
        }
        uint256 wethBefore = IERC20Min(weth).balanceOf(address(this));
        try IPairMin(pair).swap(tokenIs0 ? 0 : out, tokenIs0 ? out : 0, address(this), "") {}
        catch {
            r.failedStage = 3;
            return r;
        }
        r.wethOut = IERC20Min(weth).balanceOf(address(this)) - wethBefore;
    }

    function _reserves(address pair, bool tokenIs0) private view returns (uint256 rToken, uint256 rWeth) {
        (uint112 r0, uint112 r1,) = IPairMin(pair).getReserves();
        (rToken, rWeth) = tokenIs0 ? (uint256(r0), uint256(r1)) : (uint256(r1), uint256(r0));
    }

    function _amountOut(uint256 amountIn, uint256 reserveIn, uint256 reserveOut, uint256 feeBps)
        private
        pure
        returns (uint256)
    {
        if (amountIn == 0 || reserveIn == 0 || reserveOut == 0) return 0;
        uint256 inWithFee = amountIn * (10000 - feeBps);
        return (inWithFee * reserveOut) / (reserveIn * 10000 + inWithFee);
    }

    receive() external payable {}
}
