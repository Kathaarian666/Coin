// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

// Simulates selling a coin into its Uniswap V4 pool (research, PROJE.md step 1/4).
// Never deployed: the runtime code is put at a real holder's address through an eth_call state override, so the
// probe sells the holder's own coins and nothing is spent. First the coins are paid into the PoolManager
// (a transfer tax shows as arrived < sent), then exactly what arrived is swapped for the other currency.

interface IERC20Min {
    function balanceOf(address) external view returns (uint256);
    function transfer(address, uint256) external returns (bool);
}

struct PoolKey {
    address currency0;
    address currency1;
    uint24 fee;
    int24 tickSpacing;
    address hooks;
}

struct SwapParams {
    bool zeroForOne;
    int256 amountSpecified;
    uint160 sqrtPriceLimitX96;
}

interface IPoolManager {
    function unlock(bytes calldata data) external returns (bytes memory);
    function swap(PoolKey memory key, SwapParams memory params, bytes calldata hookData) external returns (int256);
    function sync(address currency) external;
    function settle() external payable returns (uint256);
    function take(address currency, address to, uint256 amount) external;
}

contract V4SellProbe {
    uint160 internal constant MIN_SQRT_PRICE = 4295128739;
    uint160 internal constant MAX_SQRT_PRICE = 1461446703485210103287273490975620648007449747;

    struct Result {
        uint256 sent;    // coins the holder paid in
        uint256 arrived; // coins the PoolManager got (less = transfer tax)
        uint256 out;     // other currency received for them
        uint256 used;    // coins the swap took (a partial fill or a hook can take less than arrived)
    }

    // failed: 0 ok, 1 reverted (revert data returned for diagnosis)
    function sell(address pm, PoolKey calldata key, address token, uint256 amount)
        external
        returns (Result memory r, uint8 failed, bytes memory reason)
    {
        try IPoolManager(pm).unlock(abi.encode(pm, key, token, amount)) returns (bytes memory data) {
            r = abi.decode(data, (Result));
        } catch (bytes memory err) {
            failed = 1;
            reason = err;
        }
    }

    function unlockCallback(bytes calldata data) external returns (bytes memory) {
        (address pm, PoolKey memory key, address token, uint256 amount) =
            abi.decode(data, (address, PoolKey, address, uint256));
        Result memory r;
        r.sent = amount;
        IPoolManager(pm).sync(token);
        uint256 before = IERC20Min(token).balanceOf(pm);
        IERC20Min(token).transfer(pm, amount);
        r.arrived = IERC20Min(token).balanceOf(pm) - before;
        IPoolManager(pm).settle();
        bool zeroForOne = key.currency0 == token;
        int256 delta = IPoolManager(pm).swap(
            key,
            SwapParams(zeroForOne, -int256(r.arrived), zeroForOne ? MIN_SQRT_PRICE + 1 : MAX_SQRT_PRICE - 1),
            ""
        );
        int128 a0 = int128(delta >> 128);
        int128 a1 = int128(delta);
        int128 got = zeroForOne ? a1 : a0;
        int128 paid = zeroForOne ? a0 : a1;
        r.out = got > 0 ? uint256(uint128(got)) : 0;
        r.used = paid < 0 ? uint256(uint128(-paid)) : 0;
        if (r.out > 0) IPoolManager(pm).take(zeroForOne ? key.currency1 : key.currency0, address(this), r.out);
        if (r.arrived > r.used) IPoolManager(pm).take(token, address(this), r.arrived - r.used);
        return abi.encode(r);
    }

    receive() external payable {}
}
