from ZeRO_SLMkII import ZeRO_SLMkII

def create_instance(c_instance):
    return ZeRO_SLMkII(c_instance)


from _Framework.Capabilities import *

def get_capabilities():
    return {CONTROLLER_ID_KEY: controller_id(vendor_id=4661, product_ids=[11], model_name='SL MkII'),
     PORTS_KEY: [inport(props=[NOTES_CC, REMOTE]),
                 inport(props=[NOTES_CC, REMOTE, SCRIPT]),
                 outport(props=[NOTES_CC, SYNC]),
                 outport(props=[SCRIPT])]}