#!/bin/bash

build() {
    cd ospray-studio/build || return 1
    if ! make -j ospStudio; then
        return 1
    fi
    cd ../..
    return 0
}

mode="pht"
scene="wavelet"
spp="4"
dev_mode=false
start_frame="0"

run() {
    OSP_OPTIONS="${mode}"

    if [ "$dev_mode" = true ]; then
        OSP_OPTIONS+=" --resolution 256x256"
    else
        OSP_OPTIONS+=" --resolution 1280x720"
    fi

    OSP_OPTIONS+=" --renderer pathtracer"

    if [ "$mode" = "pht" ]; then
        OSP_OPTIONS+=" --spp ${spp}"
    fi

    spp_padded=$(printf "%06d" "$spp")

    OSP_OPTIONS+=" --pixelfilter 0"
    OSP_OPTIONS+=" --image ${scene}_${spp_padded}spp"
    OSP_OPTIONS+=" --saveAlbedo"
    OSP_OPTIONS+=" --saveDepth"
    OSP_OPTIONS+=" --saveNormal"
    OSP_OPTIONS+=" --format png"

    if [ "$mode" = "pht" ]; then
        OSP_OPTIONS+=" --cameraGenerator fibonacci"
        OSP_OPTIONS+=" --cameraGeneratorFlipYZ"
        OSP_OPTIONS+=" --numFrames 20"
        OSP_OPTIONS+=" --forceOverwrite"
        OSP_OPTIONS+=" --outputPath images/${scene}_${spp_padded}spp"
        OSP_OPTIONS+=" --startFrame ${start_frame}"
    fi

    additional_options_file="ospStudio-scenes/${scene}_opts.txt"
    if [ -f "$additional_options_file" ]; then
        OSP_OPTIONS+=" $(cat "$additional_options_file")"
    fi

    if [ "$mode" = "pht" ]; then
        additional_options_file="ospStudio-scenes/${scene}_pht_opts.txt"
        if [ -f "$additional_options_file" ]; then
            OSP_OPTIONS+=" $(cat "$additional_options_file")"
        fi
    fi
    echo "Using options ${OSP_OPTIONS}"

    OSP_STUDIO_BASE="./ospray-studio/build/ospStudio"
    OSP_STUDIO_BASE+=" ${OSP_OPTIONS}"

    if [ "$scene" = "none" ]; then
        echo "Running ospStudio without any file"
        ${OSP_STUDIO_BASE}
    else
        scene_file="ospStudio-scenes/${scene}.sg"
        if [ -f "$scene_file" ]; then
            echo "Running ospStudio with ${scene_file}"
            ${OSP_STUDIO_BASE} "$scene_file"
        else
            echo "Error: Scene at path ${scene_file} not found"
            return 1
        fi
    fi

    if [ "$mode" = "gui" ] && [ "$scene" != "none" ]; then
        if [ -f "studio_scene.sg" ]; then
            echo "Updating ${scene}.sg"
            mv studio_scene.sg "ospStudio-scenes/${scene}.sg"
        fi
    fi
}

usage() {
    echo "Usage: $0 -m|--mode <mode> -s|--scene <scene> [-p|--spp <spp>] [-d|--dev-mode]"
    echo "  -m, --mode      Mode: gui or pht (required)"
    echo "  -s, --scene     Scene name (required)"
    echo "  -p, --spp       Samples per pixel (optional, default: 1)"
    echo "  -d, --dev-mode  Enable development mode (optional flag)"
    echo "  -f, --start-frame Starting frame number (optional, default: 0)"
    exit 1
}

main() {
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
        -m | --mode)
            mode="$2"
            shift 2
            ;;
        -s | --scene)
            scene="$2"
            shift 2
            ;;
        -p | --spp)
            spp="$2"
            shift 2
            ;;
        -f | --start-frame)
            start_frame="$2"
            shift 2
            ;;
        -d | --dev-mode)
            dev_mode=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
        esac
    done

    # mode must be one of: gui, pht
    if [ "$mode" != "gui" ] && [ "$mode" != "pht" ]; then
        echo "Error: mode must be one of : gui, pht"
        exit 1
    fi

    if build; then
        run
    else
        echo "Build failed"
        exit 1
    fi
}

main "$@"
