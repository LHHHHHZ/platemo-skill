function test_batch_runner(platemo_root,output_root)
%TEST_BATCH_RUNNER 小预算验证真实平台的独立保存，不改动已有 Data。
    assert(isfolder(output_root),'Create the test output directory first.');
    cfg = struct('algorithms',{{struct('class','NSGAII','label','ga','params',[]), ...
        struct('class','NSGAIII','label','reference','params',[])}}, ...
        'problems',{{struct('class','DTLZ2','M',3,'D',8)}}, ...
        'N',12, 'maxFE',24, 'runs',3, 'metrics',{{'IGD','HV'}}, 'save_count',2, ...
        'experiment_root',output_root, 'experiment_id','smoke_old');
    cd(platemo_root);
    config_path = fullfile(output_root,'test_config.json');
    writeConfig(config_path,cfg);
    run_platemo_batch(config_path);
    cfg.experiment_id = 'smoke_new';
    cfg.runs = 1;
    writeConfig(config_path,cfg);
    run_platemo_batch(config_path);
    old = jsondecode(fileread(fullfile(output_root,'smoke_old','manifest.json')));
    fresh = jsondecode(fileread(fullfile(output_root,'smoke_new','manifest.json')));
    assert(strcmp(old.status,'completed') && strcmp(fresh.status,'completed'));
    assert(numel(old.records) == 6 && numel(fresh.records) == 2);
    assert(isfile(fullfile(output_root,'smoke_old','batch_run.log')));
    assert(isfile(fullfile(output_root,'smoke_new','batch_run.log')));
    rejected = false;
    try
        run_platemo_batch(config_path);
    catch ME
        rejected = contains(ME.message,'Experiment already exists');
    end
    assert(rejected,'An existing experiment must never be overwritten.');
    fprintf('BATCH_ISOLATION_TEST_PASS old=6 new=2 overwrite_rejected=1\n');
end

function writeConfig(path,cfg)
    fid = fopen(path,'w','n','UTF-8');
    assert(fid >= 0,'Cannot create test config.');
    guard = onCleanup(@()fclose(fid)); %#ok<NASGU>
    fprintf(fid,'%s',jsonencode(cfg));
end
