from pyteal import *

def abc_contract():
    """
    ABC System Smart Contract
    Stores flagged post records on Algorand TestNet.
    
    Global state keys:
      "total_flags" -> count of all flags recorded
    
    Local state (per post, stored via box or note field):
      We use transaction notes to store post data cheaply..
    
    Operations:
      - record_flag: store a flag record (post hash, account, score)
      - get_stats:   read total flag count
    """

    # --- Handlers ---

    # record_flag operation
    # Called by backend when AI flags a post
    # Args: [0] post_hash, [1] account_id, [2] score (0-100), [3] verdict
    record_flag = Seq([
        Assert(Txn.application_args.length() == Int(4)),
        Assert(Txn.sender() == Global.creator_address()),  # only backend can write

        # Increment total flags counter
        App.globalPut(
            Bytes("total_flags"),
            App.globalGet(Bytes("total_flags")) + Int(1)
        ),

        # Store the flag record keyed by post hash
        App.globalPut(
            Txn.application_args[0],   # key = post_hash
            Concat(
                Txn.application_args[1],   # account_id
                Bytes("|"),
                Txn.application_args[2],   # score
                Bytes("|"),
                Txn.application_args[3],   # verdict
            )
        ),

        Approve()
    ])

    # on_create: initialise global state
    on_create = Seq([
        App.globalPut(Bytes("total_flags"), Int(0)),
        Approve()
    ])

    # Router
    program = Cond(
        [Txn.application_id() == Int(0),       on_create],
        [Txn.on_completion() == OnComplete.DeleteApplication, Return(Int(0))],
        [Txn.on_completion() == OnComplete.UpdateApplication, Return(Int(0))],
        [Txn.on_completion() == OnComplete.OptIn, Approve()],
        [Txn.on_completion() == OnComplete.CloseOut, Approve()],
        [Txn.application_args[0] == Bytes("record_flag"), record_flag],
    )

    return program


def clear_program():
    return Approve()


if __name__ == "__main__":
    import os
    from algosdk.v2client import algod
    from algosdk import transaction, mnemonic, account
    from dotenv import load_dotenv
    import base64

    load_dotenv()

    # Compile
    approval = compileTeal(abc_contract(), mode=Mode.Application, version=6)
    clear = compileTeal(clear_program(), mode=Mode.Application, version=6)

    # Save TEAL files
    with open("approval.teal", "w") as f:
        f.write(approval)
    with open("clear.teal", "w") as f:
        f.write(clear)

    print("✅ TEAL files written: approval.teal, clear.teal")

    # Deploy to TestNet
    algod_client = algod.AlgodClient(
        "",
        os.getenv("ALGOD_URL", "https://testnet-api.algonode.cloud"),
        headers={"X-Algo-API-Token": ""}
    )

    # Compile via algod
    def compile_program(client, source):
        result = client.compile(source)
        return base64.b64decode(result["result"])

    approval_bytes = compile_program(algod_client, approval)
    clear_bytes = compile_program(algod_client, clear)

    # Get signer account
    mn = os.getenv("ALGO_MNEMONIC")
    private_key = mnemonic.to_private_key(mn)
    sender = account.address_from_private_key(private_key)

    sp = algod_client.suggested_params()

    # Create app transaction
    txn = transaction.ApplicationCreateTxn(
        sender=sender,
        sp=sp,
        on_complete=transaction.OnComplete.NoOpOC,
        approval_program=approval_bytes,
        clear_program=clear_bytes,
        global_schema=transaction.StateSchema(num_uints=1, num_byte_slices=63),
        local_schema=transaction.StateSchema(num_uints=0, num_byte_slices=0),
    )

    signed = txn.sign(private_key)
    tx_id = algod_client.send_transaction(signed)
    print(f"📤 Deploy transaction sent: {tx_id}")

    # Wait for confirmation
    result = transaction.wait_for_confirmation(algod_client, tx_id, 4)
    app_id = result["application-index"]
    print(f"✅ Contract deployed! App ID: {app_id}")
    print(f"🔍 View on explorer: https://testnet.explorer.perawallet.app/application/{app_id}/")
    print(f"\n👉 Add this to your .env file:\nAPP_ID={app_id}")
