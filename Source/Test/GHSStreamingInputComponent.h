#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#if !PLATFORM_WASM
#include "IPixelStreaming2InputHandler.h"
#endif
#include "TimerManager.h"
#include "GHSStreamingInputComponent.generated.h"

class FMemoryReader;

/** Public PS2 API bridge. Does not depend on the engine's unexported Blueprint input class. */
UCLASS()
class UGHSStreamingInputComponent : public UActorComponent
{
    GENERATED_BODY()
public:
    DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FOnInput, const FString&, Descriptor);
    UPROPERTY() FOnInput OnInputEvent;
    void SendPixelStreamingResponse(const FString& Descriptor);
    static bool ReadDescriptor(FMemoryReader& Message, FString& Out);
protected:
    virtual void BeginPlay() override;
    virtual void EndPlay(const EEndPlayReason::Type Reason) override;
private:
    void BindStreamers();
#if !PLATFORM_WASM
    struct FBinding
    {
        TWeakPtr<IPixelStreaming2InputHandler> Handler;
        IPixelStreaming2InputHandler::MessageHandlerFn Previous;
    };
    TArray<FBinding> Bindings;
    FTimerHandle BindTimer;
#endif
};
