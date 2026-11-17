#pragma once

#include "CoreMinimal.h"

#if PLATFORM_WASM
#include "Widgets/SLeafWidget.h"

/** Same-origin DOM presentation for the HTML HUD; all UObject calls stay on the game thread. */
class SGHSWasmBrowser : public SLeafWidget
{
public:
    SLATE_BEGIN_ARGS(SGHSWasmBrowser) {}
        SLATE_ARGUMENT(FString, Document)
        SLATE_ARGUMENT(bool, Transparent)
    SLATE_END_ARGS()
    void Construct(const FArguments& Args);
    virtual ~SGHSWasmBrowser() override;
    void Bind(UObject* Target);
    void Evaluate(const FString& Script);
    static void EndFrame();
private:
    virtual FVector2D ComputeDesiredSize(float) const override { return FVector2D(480, 720); }
    virtual int32 OnPaint(const FPaintArgs&, const FGeometry&, const FSlateRect&, FSlateWindowElementList&,
        int32 LayerId, const FWidgetStyle&, bool bParentEnabled) const override;
    void Receive(const TSharedPtr<class FJsonObject>& Message);
    int32 Id = 0;
    TWeakObjectPtr<UObject> BoundTarget;
    mutable uint64 LastPaintFrame = MAX_uint64;
    mutable TSharedPtr<class FJsonObject> Layout;
};
#endif
