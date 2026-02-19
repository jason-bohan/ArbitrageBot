from bot_state import save_state, load_state

print('initial:', load_state())
print('saving test state...')
save_state({'scanner': True, 'credit_spread': False})
print('after save:', load_state())
