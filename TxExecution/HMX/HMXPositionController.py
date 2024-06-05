import os
from GlobalUtils.globalUtils import *
from GlobalUtils.logger import logger
from TxExecution.HMX.HMXPositionControllerUtils import *
from APICaller.master.MasterUtils import get_target_tokens_for_HMX
from PositionMonitor.Master.MasterPositionMonitorUtils import PositionCloseReason
from hmx2.constants.tokens import COLLATERAL_USDC
import time
from hexbytes import HexBytes

class HMXPositionController:
    def __init__(self):
        self.client = GLOBAL_HMX_CLIENT
        self.account = str(os.getenv('ADDRESS'))
        self.leverage_factor = float(os.getenv('TRADE_LEVERAGE'))

    #######################
    ### WRITE FUNCTIONS ###
    #######################

    def execute_trade(self, opportunity: dict, is_long: bool, trade_size: float):
        try:
            if not self.is_already_position_open():
                symbol = str(opportunity['symbol'])
                market = get_market_for_symbol(symbol)
                adjusted_trade_size_usd = self.calculate_adjusted_trade_size_usd(trade_size)

                
                response = self.client.private.create_market_order(
                    0,
                    market_index=market,
                    buy=is_long,
                    size=adjusted_trade_size_usd,
                    reduce_only=False,
                    tp_token=COLLATERAL_USDC
                )


                time.sleep(15)
                if not self.is_already_position_open():
                    logger.error(f'HMXPositionController - Failed to open position for symbol {symbol}.')
                    return None

                size_in_asset = get_asset_amount_for_given_dollar_amount(symbol, adjusted_trade_size_usd)
                position_details = self.handle_position_opened(symbol, size_in_asset)

                return position_details

        except Exception as e:
            logger.error(f'HMXPositionController - Error while opening trade for symbol {symbol}, Error: {e}')
            return None


    def close_all_positions(self):
        try:
            tokens = get_target_tokens_for_HMX
            for token in tokens:
                self.close_position(token, reason=PositionCloseReason.CLOSE_ALL_POSITIONS.value)
        
        except Exception as e:
            logger.error(f'HMXPositionController - Error while closing all trades. Error: {e}')
            return None

    def close_position(self, symbol: str, reason: str):
        max_retries = 2 
        retry_delay_in_seconds = 3 
        market_index = get_market_for_symbol(symbol)
        
        for attempt in range(max_retries):
            try:
                position = self.client.public.get_position_info(
                    self.account,
                    0,
                    market_index
                    )

                if position and position['position_size'] != 0:
                    close_position_details = {
                        'symbol': symbol,
                        'exchange': 'HMX',
                        'pnl': position['pnl'],
                        'accrued_funding': position['funding_fee'],
                        'reason': reason
                    }

                    size = float(position['position_size'])
                    inverse_size = size * -1
                    side = is_long(inverse_size)
                    abs_size = abs(size)
                    self.client.private.create_market_order(
                        0, 
                        market_index=market_index, 
                        buy=side, 
                        size=abs_size,
                        reduce_only=False,
                        tp_token=COLLATERAL_USDC
                    )
                    
                    time.sleep(15)
                    if self.is_already_position_open():
                        logger.error(f'HMXPositionController - Position on HMX still open 15 seconds after attempting to close. Symbol: {symbol}.')
                        return None

                    self.handle_position_closed(position_report=close_position_details)
                    logger.info(f'HMXPositionController - Position successfully closed: {close_position_details}')
                    return 
                else:
                    logger.error('HMXPositionController - Failed to close position. Please check manually.')
                    raise Exception('HMXPositionController - Commit order failed, no transaction hash returned.')

            except Exception as e:
                logger.error(f"HMXPositionController - An error occurred while trying to close a position: {e}")
                if attempt < max_retries - 1:
                    logger.info("HMXPositionController - Attempting to retry closing position after delay...")
                    time.sleep(retry_delay_in_seconds)
                else:
                    raise e


    def deposit_erc20_collateral(self, token_address: str, amount: float):
        """
        Takes amount in normalized terms - i.e. not token decimals
        eg. 100.00 = 100 USDC
        """
        try:
            self.client.private.deposit_erc20_collateral(0, COLLATERAL_USDC, 500)
            response = self.client.private.deposit_erc20_collateral(0, token_address, amount)
            tx_hash = HexBytes.hex(response['tx'])
            time.sleep(3)
            if is_transaction_hash(tx_hash):
                logger.info(f'HMXPositionController - Collateral deposit tx successful. Token Address: {token_address}, Amount = {amount}')
                return

        except Exception as e:
            logger.error(f'HMXPositionController - Failed to deposit collateral. Token Address: {token_address}, Amount: {amount}. Error: {e}')
            return None

    ######################
    ### READ FUNCTIONS ###
    ######################

    def is_already_position_open(self) -> bool:
        try:
            position_list = self.client.public.get_all_position_info(self.account, 0)
            if not position_list:
                return False
            for position in position_list: 
                if float(position['position_size']) != 0:
                    return True
            return False
        except Exception as e:
            logger.error(f"HMXPositionController - Error while checking if position is open: {e}")
            return False

    def calculate_adjusted_trade_size_usd(self, trade_size: float) -> float:
        try:
            trade_size_with_leverage = trade_size * self.leverage_factor
            adjusted_trade_size_usd = round(trade_size_with_leverage, 3)

            return adjusted_trade_size_usd
        except Exception as e:
            logger.error(f"HMXPositionController - Failed to calculate adjusted trade size. Error: {e}")
            return None

    def handle_position_opened(self, symbol: str, size_in_asset: float):
        try:
            side: str = None
            if size_in_asset > 0:
                side = "LONG"
            elif size_in_asset < 0:
                side = "SHORT"

            position = self.get_position_object(symbol, side, size_in_asset)
            return position
        
        except Exception as e:
            logger.error(f'HMXPositionController - Failed to handle position opened. Error: {e}')

    def handle_position_closed(self, position_report: dict):
        try:
            pub.sendMessage(EventsDirectory.POSITION_CLOSED.value, position_report=position_report)
            return 
        except Exception as e:
            logger.error(f"HMXPositionController - Failed to handle position closing. Error: {e}")
            return None

    def get_position_object(self, symbol: str, side: str, size: float) -> dict:
        try:
            liquidation_price = self.get_liquidation_price(symbol)
            position_object = {
                    'exchange': 'HMX',
                    'symbol': symbol,
                    'side': side,
                    'size': size,
                    'liquidation_price': liquidation_price
                }
            return position_object

        except Exception as e:
            logger.error(f"HMXPositionController - Failed to get position object for symbol {symbol}. Error: {e}")
            return None

    def get_liquidation_price(self, symbol: str) -> float:
        try:
            market_index = get_market_for_symbol(symbol)
            position = self.client.public.get_position_info(self.account, 0, market_index)
            asset_price = get_price_from_pyth(symbol)
            available_collateral = self.get_available_collateral()
            response = self.client.public.get_market_info(market_index)
            margin_details = response['margin']
            is_long_var = is_long(float(position['position_size']))
            position_size = float(position['position_size'])
            maintenance_margin_requirement = float(margin_details['maintenance_margin_fraction_bps']) * 100

            liquidation_params = {
                "position_size": position_size,
                "is_long": is_long_var,
                "available_margin": available_collateral,
                "asset_price": asset_price,
                "maintenance_margin_requirement": maintenance_margin_requirement
            }

            liquidation_price = calculate_liquidation_price(liquidation_params)
            return liquidation_price

        except Exception as e:
            logger.error(f"HMXPositionController - Failed to get liquidation price for symbol: {symbol}. Error: {e}")
            return None


    def get_available_collateral(self) -> float:
        try:
            available_collateral = self.client.public.get_collateral_usd(self.account, 0)
            return float(available_collateral)

        except Exception as e:
            logger.error(f"HMXPositionController - Failed to get available collateral. Error: {e}")
            return None


# x = HMXPositionController()
# x.close_position('ARB', PositionCloseReason.TEST.value)
# print(x.is_already_position_open())